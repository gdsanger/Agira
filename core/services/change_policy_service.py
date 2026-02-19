"""
Service for managing Change Policy and automatic approver assignment.
"""
from typing import Optional, Set, List, Dict
import logging
from django.db import transaction
from core.models import (
    Change, ChangePolicy, ChangeApproval, ChangePolicyRole,
    UserRole, User, ApprovalStatus, UserOrganisation
)

logger = logging.getLogger(__name__)


class ChangePolicyService:
    """Service for handling change policy logic and approver synchronization."""
    
    @staticmethod
    def get_users_with_role_in_change_orgs(change: Change, role: str) -> List[User]:
        """
        Get users who have the specified role in at least one of the change's organisations.
        
        Uses UserOrganisation.role (organization-specific role) instead of User.role.
        
        Args:
            change: The Change instance to check organizations for
            role: The role to filter by (from UserRole choices)
            
        Returns:
            List of User objects that have the role in any of the change's organizations
        """
        # Get change organization IDs
        change_org_ids = list(change.organisations.values_list('id', flat=True))
        
        if not change_org_ids:
            return []

        # Find users with the specified role in at least one of the change's organizations
        users = User.objects.filter(
            active=True,
            user_organisations__organisation_id__in=change_org_ids,
            user_organisations__role=role
        ).distinct()
        
        return list(users)
    
    @staticmethod
    def get_approver_role_in_change_context(change: Change, user: User) -> Optional[str]:
        """
        Get the role of a user in the context of a change's organizations.
        
        If the user has roles in multiple change organizations, returns the highest priority role.
        Priority order: ISB > MGMT > APPROVER > INFO > DEV > AGENT > USER
        
        Args:
            change: The Change instance
            user: The User instance
            
        Returns:
            Role string from UserRole choices, or None if user has no role in change orgs
        """
        change_org_ids = list(change.organisations.values_list('id', flat=True))
        
        if change_org_ids:
            # Get user's roles in the change's organizations
            user_roles = UserOrganisation.objects.filter(
                user=user,
                organisation_id__in=change_org_ids
            ).values_list('role', flat=True).distinct()
        else:
            # If change has no organizations, use any of the user's org roles
            user_roles = UserOrganisation.objects.filter(
                user=user
            ).values_list('role', flat=True).distinct()
        
        if not user_roles:
            return None
        
        # Define role priority (higher index = higher priority)
        role_priority = {
            UserRole.USER: 0,
            UserRole.AGENT: 1,
            UserRole.DEV: 2,
            UserRole.INFO: 3,
            UserRole.APPROVER: 4,
            UserRole.MGMT: 5,
            UserRole.ISB: 6,
        }
        
        # Return the highest priority role
        return max(user_roles, key=lambda r: role_priority.get(r, -1))
    
    @staticmethod
    def find_matching_policy(change: Change) -> Optional[ChangePolicy]:
        """
        Find the ChangePolicy that matches the given change's criteria.
        
        Args:
            change: The Change instance to find a policy for
            
        Returns:
            ChangePolicy if found, None otherwise
        """
        # Build query based on change attributes
        query = ChangePolicy.objects.filter(
            risk_level=change.risk,
            security_relevant=change.is_safety_relevant
        )
        
        # Handle release type matching
        if change.release_id and change.release.type:
            # Prefer release-specific policy, but fall back to generic policy (release_type is null)
            specific_policy = query.filter(release_type=change.release.type).first()
            if specific_policy:
                return specific_policy
            return query.filter(release_type__isnull=True).first()

        # No release or release without type: use generic policy
        return query.filter(release_type__isnull=True).first()
    
    @staticmethod
    def get_required_roles(policy: Optional[ChangePolicy]) -> Set[str]:
        """
        Get the set of required roles for a change based on the policy.
        
        Args:
            policy: The ChangePolicy to get roles from (can be None)
            
        Returns:
            Set of role strings
        """
        required_roles = set()
        
        # Add roles from policy if one was found
        if policy:
            policy_roles = policy.policy_roles.values_list('role', flat=True)
            required_roles.update(policy_roles)
        
        return required_roles
    
    @staticmethod
    @transaction.atomic
    def sync_change_approvers(change: Change) -> dict:
        """
        Synchronize change approvers based on the matching policy.
        
        This function:
        1. Finds the matching policy for the change
        2. Determines required roles (INFO and DEV always; APPROVER only if in policy)
        3. Ensures ALL users with required roles from ALL change organizations are assigned as approvers,
           tracked per (user_id, role) pair
        4. For INFO/DEV approvals: sets is_required=False, notes="Nur zur Info",
           status=INFO, approved_at=now()
        5. Removes obsolete (user_id, role) pairs only if approved_at IS NULL
        6. Uses UserOrganisation.role (organization-specific roles) for all role checks
        
        Args:
            change: The Change instance to sync approvers for
            
        Returns:
            Dict with sync results: {
                'policy_found': bool,
                'required_roles': set,
                'approvers_added': int,
                'approvers_removed': int
            }
        """
        from django.utils import timezone

        # Find matching policy
        policy = ChangePolicyService.find_matching_policy(change)

        # Get required roles from policy only
        required_roles = ChangePolicyService.get_required_roles(policy)

        # Determine sync_roles: always include INFO and DEV; APPROVER only if in required_roles
        always_roles = {UserRole.INFO, UserRole.DEV}
        sync_roles = always_roles | required_roles

        # Track changes
        approvers_added = 0
        approvers_removed = 0

        # Build target set: {(user_id, role)} from UserOrganisation in a single query
        target: Set[tuple] = set()
        change_org_ids = list(change.organisations.values_list('id', flat=True))
        user_ids_by_role: Dict[str, Set[int]] = {role: set() for role in sync_roles}

        if change_org_ids:
            org_roles = UserOrganisation.objects.filter(
                organisation_id__in=change_org_ids,
                role__in=sync_roles,
                user__active=True,
            ).values_list('user_id', 'role').distinct()

            for user_id, role in org_roles:
                user_ids_by_role[role].add(user_id)
                target.add((user_id, role))

        for role in sync_roles:
            if not user_ids_by_role[role]:
                logger.warning(
                    f"No user found with org-role {role} in change organizations "
                    f"for change {change.id}"
                )

        # Get existing approvals keyed by (approver_id, role)
        existing_approvals = ChangeApproval.objects.filter(change=change).select_related('approver')
        existing_map = {(a.approver_id, a.role): a for a in existing_approvals}

        # Add missing (user_id, role) pairs
        approvals_to_create = []
        now = timezone.now()
        for (user_id, role) in target:
            if (user_id, role) not in existing_map:
                is_info_or_dev = role in (UserRole.INFO, UserRole.DEV)
                create_kwargs = dict(
                    change=change,
                    approver_id=user_id,
                    role=role,
                    is_required=not is_info_or_dev,
                    status=ApprovalStatus.INFO if is_info_or_dev else ApprovalStatus.PENDING,
                    notes="Nur zur Info" if is_info_or_dev else "",
                    approved_at=now if is_info_or_dev else None,
                )
                # Use create() (not bulk_create) so model save hooks/defaults are applied
                # (e.g. unique decision_token generation).
                ChangeApproval.objects.create(**create_kwargs)
                approvers_added += 1

        # Remove obsolete (user_id, role) pairs that are no longer in target,
        # but only if no decision has been made (approved_at IS NULL)
        for (key, approval) in list(existing_map.items()):
            if key not in target:
                if approval.approved_at is None:
                    logger.info(
                        f"Removing approver {approval.approver.username} with role {approval.role} "
                        f"for change {change.id} (no longer required and no decision made)"
                    )
                    approval.delete()
                    approvers_removed += 1
                else:
                    logger.info(
                        f"Keeping approver {approval.approver.username} with role {approval.role} "
                        f"for change {change.id} (decision already made at: {approval.approved_at})"
                    )

        return {
            'policy_found': policy is not None,
            'policy': policy,
            'required_roles': required_roles,
            'approvers_added': approvers_added,
            'approvers_removed': approvers_removed
        }
