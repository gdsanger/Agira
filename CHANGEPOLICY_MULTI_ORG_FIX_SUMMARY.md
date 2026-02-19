# Change Policy Approver Assignment Fix - Implementation Summary

## Issue Reference
- **Issue:** gdsanger/Agira#460
- **Related Issues:** gdsanger/Agira#591, gdsanger/Agira#592
- **Date:** February 19, 2026

## Problem Statement
The system was not correctly assigning approvers when a Change had multiple organizations. Specifically:

**Observed Behavior:**
- A Change with 6 organizations
- ChangePolicy requires role "APPROVER" 
- Each organization has at least one user with APPROVER role
- **Only 1 approver was being assigned**

**Expected Behavior:**
- ALL users with the required role from ALL organizations should be assigned as approvers

## Root Cause
In `core/services/change_policy_service.py`, the `sync_change_approvers` method had flawed logic:

```python
# OLD CODE (Lines 202-218)
for required_role in required_roles:
    if required_role not in existing_roles or not existing_roles[required_role]:
        users_with_role = ChangePolicyService.get_users_with_role_in_change_orgs(
            change, required_role
        )
        if users_with_role:
            user_with_role = users_with_role[0]  # ❌ ONLY FIRST USER
            ChangeApproval.objects.create(...)
```

**Two Problems:**
1. Only added approvers if NO approver existed for that role (`if required_role not in existing_roles`)
2. When adding, only added the first user (`users_with_role[0]`)

## Solution Implementation

### 1. Changed Approver Assignment Logic
Rewrote `sync_change_approvers` to collect and assign ALL users:

```python
# NEW CODE (Lines 193-221)
users_that_should_be_approvers = set()

# For each required role, find ALL users with that role in change organizations
for required_role in required_roles:
    users_with_role = ChangePolicyService.get_users_with_role_in_change_orgs(
        change, required_role
    )
    for user in users_with_role:  # ✓ ALL USERS
        users_that_should_be_approvers.add(user.id)

# Add missing approvers
for user_id in users_that_should_be_approvers:
    if user_id not in existing_approver_ids:
        # Create approval entry
        ChangeApproval.objects.create(...)
```

### 2. Added Auto Token Generation
Added `save()` override to `ChangeApproval` model to prevent constraint violations:

```python
def save(self, *args, **kwargs):
    """Override save to automatically generate decision token."""
    self.ensure_token()
    super().save(*args, **kwargs)
```

This ensures every approval has a unique `decision_token` even when creating multiple approvals.

### 3. Updated Removal Logic
Modified the removal logic to check individual approvers instead of roles:

```python
# Check each existing approval
for approval in existing_approvals:
    if approval.approver_id not in users_that_should_be_approvers:
        # Only remove if no decision has been made
        if approval.approved_at is None:
            approval.delete()
```

## Test Coverage

### New Test: `test_all_approvers_from_all_orgs_with_same_role`
Comprehensive test demonstrating the fix:

**Setup:**
- 6 organizations
- Each org has: 2 APPROVER users, 1 INFO user, 1 DEV user
- Total: 12 APPROVERs, 6 INFO, 6 DEV
- ChangePolicy requires APPROVER role (INFO and DEV are mandatory)

**Expected Result:** 24 total approvals (12 + 6 + 6)

**Test Output:**
```
INFO Added approver approver_org1_1 with org-role Approver
INFO Added approver approver_org1_2 with org-role Approver
...
INFO Added approver info_org6 with org-role Info
INFO Added approver dev_org6 with org-role Development
✓ ok
```

### All Existing Tests Pass
- ✓ `test_get_users_with_role_in_change_orgs` - Role resolution
- ✓ `test_get_users_ignores_global_role` - Org-specific roles
- ✓ `test_get_approver_role_in_change_context` - Role context
- ✓ `test_sync_change_approvers_uses_org_roles` - Org roles usage
- ✓ `test_sync_does_not_remove_decided_approvers` - Decision preservation
- ✓ `test_change_with_multiple_orgs_finds_all_approvers` - Multi-org handling

## Files Modified

### 1. `core/services/change_policy_service.py`
**Changes:**
- Rewrote `sync_change_approvers` method (lines 154-263)
- Updated docstring to reflect new behavior
- Changed from role-based grouping to user-based collection
- Total: ~60 lines modified

**Key Changes:**
- Collect ALL users with required roles
- Assign ALL collected users as approvers
- Simplified removal logic

### 2. `core/models.py`
**Changes:**
- Added `save()` override to `ChangeApproval` class (lines 520-523)
- Auto-generates decision tokens on save
- Total: 5 lines added

### 3. `core/test_change_policy_service.py`
**Changes:**
- Added comprehensive multi-org test
- Tests 6 organizations with multiple users per role
- Validates all 24 approvers are assigned
- Total: 130 lines added

## Impact Analysis

### Positive Impact
1. **Complete Coverage:** All stakeholders from all organizations are now included
2. **No Missing Approvers:** Prevents approval bottlenecks from missing approvers
3. **Correct Workflow:** Approval workflows now include all necessary participants
4. **Scalable:** Works with any number of organizations and users

### Backward Compatibility
- ✓ No breaking changes to API
- ✓ Existing approvals preserved
- ✓ Decision dates still protected (decided approvers not removed)
- ✓ All existing tests pass

### Performance Considerations
- Slight increase in database writes (more approvals created)
- No change to query complexity (already iterating through roles)
- Atomic transactions ensure consistency

## Verification

### Manual Testing
1. Create a Change with multiple organizations
2. Assign multiple users with APPROVER role in each organization
3. Save the Change (triggers `sync_change_approvers`)
4. Verify ALL approvers from ALL organizations are assigned

### Expected Behavior
```
Change with 3 organizations:
- Org A: 2 APPROVERs, 1 INFO, 1 DEV
- Org B: 2 APPROVERs, 1 INFO, 1 DEV  
- Org C: 2 APPROVERs, 1 INFO, 1 DEV

Total assigned: 12 approvals (6 APPROVER + 3 INFO + 3 DEV)
```

## Deployment Notes

### Database Changes
- No migrations required
- Uses existing `ChangeApproval` table
- Auto token generation happens in application layer

### Configuration Changes
- None required

### Monitoring
- Check logs for "Added approver" messages
- Monitor approval counts per change
- Verify no "No user found with org-role" warnings

## References

### Related Code
- `ChangePolicyService.get_users_with_role_in_change_orgs()` - Finds users with specific role
- `ChangePolicyService.get_approver_role_in_change_context()` - Gets user's role in change context
- `ChangePolicyService.find_matching_policy()` - Finds applicable policy
- `ChangePolicyService.get_required_roles()` - Gets required roles from policy

### Related Tests
- `core/test_change_policy_service.py` - All policy tests
- Focus on `ChangePolicyMultiOrgTestCase` class

### Integration Points
- `core/views.py` - Calls `sync_change_approvers` on Change create/update
- Change save triggers automatic approver synchronization

## Conclusion

This fix ensures that the ChangePolicy system correctly handles multi-organization scenarios by:
1. Assigning ALL users with required roles from ALL organizations
2. Maintaining backward compatibility
3. Preserving existing approval decisions
4. Providing comprehensive test coverage

The implementation is minimal, focused, and solves the exact problem described in the issue without introducing unnecessary complexity.
