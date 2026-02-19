"""
Service for managing Change Policy and automatic approver assignment.
"""
from typing import Optional, Set, List
import logging
from django.db import transaction
from django.db.models import Q
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
        
        if change_org_ids:
            # Find users with the specified role in at least one of the change's organizations
            users = User.objects.filter(
                active=True,
                user_organisations__organisation_id__in=change_org_ids,
                user_organisations__role=role
            ).distinct()
        else:
            # If change has no organizations, find users with the role in any organization
            # This allows policy application even when organizations are not yet determined
            users = User.objects.filter(
                active=True,
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
        if change.release_id:
            # Change has a release - match on release type
            if change.release.type:
                query = query.filter(release_type=change.release.type)
            else:
                # Release exists but has no type - no policy will match
                return None
        else:
            # Change has no release - match policies with null release_type
            query = query.filter(release_type__isnull=True)
        
        # Return first matching policy (should be unique due to constraint)
        return query.first()
    
    @staticmethod
    def get_required_roles(policy: Optional[ChangePolicy]) -> Set[str]:
        """
        Get the set of required roles for a change based on the policy.
        Always includes INFO and DEV roles.
        
        Args:
            policy: The ChangePolicy to get roles from (can be None)
            
        Returns:
            Set of role strings
        """
        # Start with mandatory roles
        required_roles = {UserRole.INFO, UserRole.DEV}
        
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
        2. Determines required roles (including mandatory INFO and DEV)
        3. Ensures at least one approver exists for each required role
        4. Removes obsolete approvers (only those without a decision)
        5. Uses UserOrganisation.role (organization-specific roles) for all role checks
        
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
        # Find matching policy
        policy = ChangePolicyService.find_matching_policy(change)
        
        # Get required roles
        required_roles = ChangePolicyService.get_required_roles(policy)
        
        # Track changes
        approvers_added = 0
        approvers_removed = 0
        
        # Get existing approvals
        existing_approvals = ChangeApproval.objects.filter(change=change).select_related('approver')
        
        # Build a map of existing roles and their approvers
        # Note: We now get roles from UserOrganisation in the change context
        existing_roles = {}
        for approval in existing_approvals:
            # Get the approver's role in the context of this change's organizations
            role = ChangePolicyService.get_approver_role_in_change_context(change, approval.approver)
            if role:
                if role not in existing_roles:
                    existing_roles[role] = []
                existing_roles[role].append(approval)
        
        # Ensure at least one approver exists for each required role
        for required_role in required_roles:
            if required_role not in existing_roles or not existing_roles[required_role]:
                # No approver for this role - find users with this role in change organizations
                users_with_role = ChangePolicyService.get_users_with_role_in_change_orgs(
                    change, required_role
                )
                
                if users_with_role:
                    # Take the first user with this role
                    user_with_role = users_with_role[0]
                    # Create approval entry
                    ChangeApproval.objects.create(
                        change=change,
                        approver=user_with_role,
                        is_required=True,
                        status=ApprovalStatus.PENDING
                    )
                    approvers_added += 1
                    logger.info(
                        f"Added approver {user_with_role.username} with org-role {required_role} "
                        f"for change {change.id}"
                    )
                else:
                    logger.warning(
                        f"No user found with org-role {required_role} in change organizations "
                        f"for change {change.id}"
                    )
        
        # Remove obsolete approvers (only if they haven't made a decision)
        # An approver has made a decision if approved_at is set
        for role, approvals in existing_roles.items():
            if role not in required_roles:
                # This role is no longer required
                for approval in approvals:
                    # Only remove if no decision has been made (approved_at is null)
                    if approval.approved_at is None:
                        logger.info(
                            f"Removing approver {approval.approver.username} with role {role} "
                            f"for change {change.id} (no longer required and no decision made)"
                        )
                        approval.delete()
                        approvers_removed += 1
                    else:
                        logger.info(
                            f"Keeping approver {approval.approver.username} with role {role} "
                            f"for change {change.id} (decision already made at: {approval.approved_at})"
                        )
        
        return {
            'policy_found': policy is not None,
            'policy': policy,
            'required_roles': required_roles,
            'approvers_added': approvers_added,
            'approvers_removed': approvers_removed
        }
