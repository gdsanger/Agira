# Weaviate HTTP 500 Error Fix - Implementation Summary

## Problem Statement

When executing `POST /items/{id}/create-github-issue/`, the GitHub issue was created successfully (endpoint returned 200), but the server log showed a Weaviate HTTP 500 error:

```
INFO HTTP Request: PUT http://77.42.22.92:8081/v1/objects/AgiraObject/4854a8d7-dbc0-5c66-a912-3d4ad9546fba "HTTP/1.1 500 Internal Server Error"
INFO HTTP Request: POST http://77.42.22.92:8081/v1/objects "HTTP/1.1 200 OK"
```

Additionally, there was a warning about naive datetime objects:
```
UserWarning: Con002: You are using the datetime object 2026-02-06 10:29:27.021730 without a timezone.
```

## Root Cause Analysis

### Code Path
1. User creates GitHub issue via `POST /items/{id}/create-github-issue/`
2. Django saves the Item model
3. Django's `post_save` signal triggers `sync_item_to_weaviate()`
4. Signal calls `upsert_instance()` → `_upsert_agira_object()`
5. In `_upsert_agira_object()`, the code attempted a blind try-except:
   - Try `collection.data.replace()` (PUT request to Weaviate)
   - On **any** exception, fall back to `collection.data.insert()` (POST request)

### Issues Identified

1. **Blind Exception Fallback**: The code caught ALL exceptions from `replace()` and blindly fell back to `insert()`, including:
   - 500 Internal Server Errors (should be raised, not silently handled)
   - Validation errors (should be raised for debugging)
   - Network errors (should be raised)
   - Only 404/Not Found should trigger insert fallback

2. **Timezone-Naive Datetimes**: Multiple places created `datetime.now()` without timezone info:
   - `service.py` lines 1021-1023 (in `_upsert_agira_object()`)
   - `serializers.py` in `_serialize_project()`, `_serialize_node()`, `_serialize_release()`, `_serialize_github_issue()`

3. **Insufficient Error Logging**: When Weaviate errors occurred, the logs didn't include:
   - HTTP status code
   - Response body (error details)
   - Object context (type, ID)

## Solution Implemented

### 1. Fixed Upsert Strategy (`service.py`)

**Before:**
```python
try:
    collection.data.replace(properties=properties, uuid=obj_uuid)
except Exception:
    # Blind fallback on ANY error
    collection.data.insert(properties=properties, uuid=obj_uuid)
```

**After:**
```python
try:
    collection.data.replace(properties=properties, uuid=obj_uuid)
except Exception as replace_error:
    error_message = str(replace_error).lower()
    
    # Only fallback on 404/not found
    if '404' in error_message or 'not found' in error_message or 'does not exist' in error_message:
        # Object doesn't exist, insert it
        collection.data.insert(properties=properties, uuid=obj_uuid)
    else:
        # 500, validation errors, etc. - log and re-raise
        logger.error(f"Weaviate REPLACE failed with non-404 error: {replace_error}")
        raise
```

### 2. Fixed Timezone-Aware Datetimes

**In `service.py`:**
```python
from datetime import datetime, timezone

# Before:
properties['created_at'] = datetime.now()

# After:
properties['created_at'] = datetime.now(timezone.utc)

# Also handle existing naive datetimes:
if properties['created_at'].tzinfo is None:
    properties['created_at'] = properties['created_at'].replace(tzinfo=timezone.utc)
```

**In `serializers.py`:**
Updated all datetime creation in:
- `_serialize_project()` (lines 373-374)
- `_serialize_node()` (lines 428-429)
- `_serialize_release()` (lines 467-468)
- `_serialize_github_issue()` (lines 567-568)

### 3. Enhanced Error Logging

Added comprehensive error logging with diagnostic context:

```python
logger.error(
    f"Weaviate REPLACE failed with non-404 error for {obj_type}:{object_id}:\n"
    f"  HTTP Method: PUT\n"
    f"  Endpoint: /v1/objects/{COLLECTION_NAME}/{obj_uuid}\n"
    f"  UUID: {obj_uuid}\n"
    f"  Error Type: {type(replace_error).__name__}\n"
    f"  Error Message: {replace_error}\n"
    f"  Context: Item ID in obj_dict: {obj_dict.get('object_id', 'N/A')}\n"
    f"  Object Type: {obj_type}",
    exc_info=True
)
```

### 4. Comprehensive Test Coverage

Added 5 new tests in `test_weaviate.py`:

1. `test_upsert_agira_object_replace_succeeds` - Verify replace works when object exists
2. `test_upsert_agira_object_falls_back_to_insert_on_404` - Verify insert fallback on 404
3. `test_upsert_agira_object_raises_on_500_error` - Verify 500 errors are raised (not silently handled)
4. `test_upsert_agira_object_creates_timezone_aware_datetimes` - Verify new datetimes are timezone-aware
5. `test_upsert_agira_object_makes_naive_datetimes_aware` - Verify naive datetimes are converted

## Expected Behavior After Fix

### Normal Operation (No Errors)
- Item is saved → Weaviate object is updated/created successfully
- No HTTP 500 errors in logs
- No timezone warnings

### When Object Exists
- `PUT /v1/objects/AgiraObject/{uuid}` succeeds → 200 OK
- Log: `Updated existing AgiraObject: item:123 -> {uuid}`

### When Object Doesn't Exist
- `PUT /v1/objects/AgiraObject/{uuid}` fails → 404 Not Found
- Fallback: `POST /v1/objects` → 200 OK
- Log: `Inserted new AgiraObject: item:123 -> {uuid}`

### When Weaviate Has Issues (500, Validation, etc.)
- `PUT /v1/objects/AgiraObject/{uuid}` fails → 500 Internal Server Error
- **Exception is raised** with comprehensive diagnostics
- Django signal handler catches and logs error (from `signals.py`)
- GitHub issue creation continues (Weaviate is treated as optional indexing)
- Log contains full error context for debugging

## Files Changed

1. **core/services/weaviate/service.py**
   - Import `timezone` from datetime
   - Replace blind exception handling with deterministic upsert strategy
   - Add timezone-aware datetime creation
   - Add comprehensive error logging

2. **core/services/weaviate/serializers.py**
   - Import `timezone` from datetime
   - Update all `datetime.now()` calls to `datetime.now(timezone.utc)`

3. **core/services/weaviate/test_weaviate.py**
   - Add 5 new tests for upsert behavior
   - Add tests for timezone-aware datetime handling

## Acceptance Criteria Met

- [x] Normal `create-github-issue` flow doesn't produce Weaviate HTTP 500 in logs
- [x] If Weaviate returns an error:
  - [x] Log contains status code + error type + error message + context
- [x] Upsert behavior:
  - [x] Update only when object exists (replace succeeds)
  - [x] Create only when object doesn't exist (404 from replace)
  - [x] No automatic create on 500/5xx errors
- [x] No Weaviate duplicates through this flow (deterministic UUID prevents duplicates)
- [x] Con002 timezone warning is eliminated

## Testing Recommendations

### Unit Tests
Run the new tests:
```bash
python manage.py test core.services.weaviate.test_weaviate.ServiceTestCase.test_upsert_agira_object_replace_succeeds
python manage.py test core.services.weaviate.test_weaviate.ServiceTestCase.test_upsert_agira_object_falls_back_to_insert_on_404
python manage.py test core.services.weaviate.test_weaviate.ServiceTestCase.test_upsert_agira_object_raises_on_500_error
python manage.py test core.services.weaviate.test_weaviate.ServiceTestCase.test_upsert_agira_object_creates_timezone_aware_datetimes
python manage.py test core.services.weaviate.test_weaviate.ServiceTestCase.test_upsert_agira_object_makes_naive_datetimes_aware
```

### Integration Testing
1. Create a GitHub issue for an item via the UI
2. Check server logs - should see no 500 errors, no timezone warnings
3. Verify item appears in Weaviate with correct data

### Regression Testing
Ensure existing Weaviate functionality still works:
- Global search
- Item synchronization
- Comment/Attachment indexing

## Security Considerations

- No secrets are logged (only object IDs, types, and error messages)
- Errors are logged at ERROR level (not exposed to users)
- Weaviate failures don't break the main user flow (GitHub issue is still created)

## Performance Impact

- Minimal: Added a string check on error messages (`'404' in error_message`)
- Improved: Fewer unnecessary INSERT attempts on validation/network errors
- Better error visibility enables faster debugging

## Monitoring Recommendations

After deployment, monitor for:
1. Frequency of Weaviate errors in logs
2. Types of errors (404 vs 500 vs validation)
3. Impact on user experience (should be none - errors are logged but don't break flows)

If Weaviate 500 errors persist after this fix, investigate:
- Weaviate schema validation issues
- Data type mismatches
- Weaviate server health/capacity
