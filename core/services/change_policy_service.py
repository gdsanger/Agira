"""
Service for managing Change Policy and automatic approver assignment.
"""
from typing import Optional, Set
import logging
from django.db import transaction
from core.models import (
    Change, ChangePolicy, ChangeApproval, ChangePolicyRole,
    UserRole, User
)

logger = logging.getLogger(__name__)


class ChangePolicyService:
    """Service for handling change policy logic and approver synchronization."""
    
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
        4. Removes obsolete approvers (only those without approval)
        
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
        existing_roles = {}
        for approval in existing_approvals:
            role = approval.approver.role
            if role not in existing_roles:
                existing_roles[role] = []
            existing_roles[role].append(approval)
        
        # Ensure at least one approver exists for each required role
        for required_role in required_roles:
            if required_role not in existing_roles or not existing_roles[required_role]:
                # No approver for this role - we need to add a placeholder
                # In a real system, you would select a specific user based on role
                # For now, we'll find the first user with this role
                user_with_role = User.objects.filter(role=required_role).first()
                
                if user_with_role:
                    # Create approval entry
                    ChangeApproval.objects.create(
                        change=change,
                        approver=user_with_role,
                        is_required=True,
                        status='Pending'
                    )
                    approvers_added += 1
                    logger.info(
                        f"Added approver {user_with_role.username} with role {required_role} "
                        f"for change {change.id}"
                    )
                else:
                    logger.warning(
                        f"No user found with role {required_role} for change {change.id}"
                    )
        
        # Remove obsolete approvers (only if they haven't approved)
        for role, approvals in existing_roles.items():
            if role not in required_roles:
                # This role is no longer required
                for approval in approvals:
                    # Only remove if not approved
                    if not approval.approved and not approval.approved_at:
                        logger.info(
                            f"Removing approver {approval.approver.username} with role {role} "
                            f"for change {change.id} (no longer required and not approved)"
                        )
                        approval.delete()
                        approvers_removed += 1
                    else:
                        logger.info(
                            f"Keeping approver {approval.approver.username} with role {role} "
                            f"for change {change.id} (already approved)"
                        )
        
        return {
            'policy_found': policy is not None,
            'policy': policy,
            'required_roles': required_roles,
            'approvers_added': approvers_added,
            'approvers_removed': approvers_removed
        }
