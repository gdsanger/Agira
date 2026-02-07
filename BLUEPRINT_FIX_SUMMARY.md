# Blueprint Import/Export Bug Fix - Summary

## Issue Description

Two critical bugs were preventing Blueprint functionality from working:

1. **Blueprint Update (500 Error)**
   - URL: `POST /configuration/blueprints/<uuid>/update/`
   - Error: "Internal Server Error" in browser console
   - Affected: Saving/updating blueprints

2. **Blueprint Export (500 Error)**
   - URL: `GET /configuration/blueprints/<uuid>/export/`
   - Error: Page shows `{"success": false, "error": "An unexpected error occurred"}`
   - Affected: Exporting blueprints as JSON

## Root Causes Identified

### Primary Issue: ActivityService.log() 
Located in `core/services/activity/service.py`, line 94:

The ActivityService was manually setting the `created_at` field:
```python
activity_data = {
    'verb': verb,
    'actor': actor,
    'summary': summary or '',
    'created_at': timezone.now(),  # ❌ This line was the problem
}
```

However, the Activity model defines `created_at` with `auto_now_add=True`:
```python
class Activity(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
```

When Django's ORM tries to create an Activity with a manually-set `auto_now_add` field, it causes a database constraint error.

### Secondary Issue: UUID Primary Keys

The `IssueBlueprint` model uses UUID primary keys:
```python
class IssueBlueprint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
```

But the `Activity` model's GenericForeignKey was using a `PositiveIntegerField` for `target_object_id`:
```python
class Activity(models.Model):
    target_object_id = models.PositiveIntegerField()  # ❌ Can't store UUIDs
```

This caused "Python int too large to convert to SQLite INTEGER" errors when trying to log activities for blueprints.

## Solution Implemented

### 1. Removed Manual created_at Assignment
**File:** `core/services/activity/service.py`

Removed the manual `created_at` assignment since Django sets it automatically:
```python
activity_data = {
    'verb': verb,
    'actor': actor,
    'summary': summary or '',
    # 'created_at': timezone.now(),  # Removed this line
}
```

### 2. Changed Activity Model Field Type
**File:** `core/models.py`

Changed `target_object_id` from `PositiveIntegerField` to `CharField`:
```python
class Activity(models.Model):
    target_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_object_id = models.CharField(max_length=255)  # Changed from PositiveIntegerField
    target = GenericForeignKey('target_content_type', 'target_object_id')
```

This allows Activity to work with both integer IDs (for most models) and UUID IDs (for blueprints).

### 3. Updated ActivityService to Use String IDs
**File:** `core/services/activity/service.py`

Updated the service to convert all object IDs to strings:
```python
# When setting target
activity_data['target_object_id'] = str(target.pk)

# When filtering
target_object_id=str(item.pk)
```

### 4. Updated Tests
**File:** `core/services/activity/test_activity.py`

Updated test assertions to expect string values:
```python
# Before
self.assertEqual(activity.target_object_id, self.item.pk)

# After  
self.assertEqual(activity.target_object_id, str(self.item.pk))
```

### 5. Created Database Migration
**File:** `core/migrations/0046_alter_activity_target_object_id.py`

Created a migration to update the database schema from PositiveIntegerField to CharField.

## Testing Results

### Blueprint Import/Export Tests
✅ All 22 tests passing
- Export tests (5 tests)
- Import tests (11 tests)
- Roundtrip tests (2 tests)
- View tests (4 tests)

### Activity Service Tests
✅ All 27 tests passing
- Log tests (10 tests)
- Status change tests (4 tests)
- Created tests (4 tests)
- Latest/filtering tests (9 tests)

### Security Check
✅ CodeQL analysis: 0 alerts

### Code Review
✅ No issues found

## Files Modified

1. `core/services/activity/service.py` - Removed manual created_at, updated to use string IDs
2. `core/models.py` - Changed Activity.target_object_id field type
3. `core/services/activity/test_activity.py` - Updated tests for string IDs
4. `core/migrations/0046_alter_activity_target_object_id.py` - Database migration

## Impact Assessment

### Positive Impact
- ✅ Blueprint update now works correctly
- ✅ Blueprint export now works correctly
- ✅ Activity logging supports models with UUID primary keys
- ✅ All existing functionality preserved

### Breaking Changes
- None. The CharField can store both integer and UUID values as strings.
- Existing integer IDs will be automatically converted to strings by Django.

### Performance Impact
- Minimal. CharField with max_length=255 is efficient for storing IDs.
- Query performance remains the same for filtering and lookups.

## References
- Fixes gdsanger/Agira#442
- Fixes gdsanger/Agira#443
- Related to gdsanger/Agira#333

## Verification Steps

To verify the fix works:

1. **Blueprint Update:**
   - Navigate to a blueprint detail page
   - Click "Edit"
   - Make changes and click "Save"
   - Verify no 500 error occurs
   - Verify success message appears

2. **Blueprint Export:**
   - Navigate to a blueprint detail page
   - Click "Export"
   - Verify JSON file downloads instead of error page
   - Verify JSON contains correct blueprint data

3. **Activity Logging:**
   - Check activity stream after blueprint operations
   - Verify activities are logged correctly
   - Verify activity targets resolve to correct blueprints
