# Weaviate Service Logging Integration

## Overview

This implementation adds comprehensive logging to the Weaviate core service to log all messages (info, debug, warn, error) as specified in issue #258 (referencing logging requirements from issue #400).

## Implementation Details

### Changes Made

**File Modified**: `core/services/weaviate/service.py`

Added comprehensive logging throughout the weaviate service with 44 total logging statements:
- **16 INFO-level logs**: Entry/exit points of major operations
- **11 DEBUG-level logs**: Detailed operation tracking
- **7 WARNING-level logs**: Expected error conditions
- **10 ERROR-level logs**: Unexpected errors with full stack traces

### Logging Coverage by Function

All major public functions now have logging:

| Function | Logging Levels | Purpose |
|----------|---------------|---------|
| `upsert_document` | INFO, DEBUG, ERROR | Logs document upsert operations |
| `delete_document` | INFO, DEBUG, WARNING, ERROR | Logs document deletion |
| `query` | INFO, DEBUG, ERROR | Logs semantic search queries |
| `global_search` | INFO, DEBUG, WARNING, ERROR | Logs global search operations |
| `ensure_schema` | INFO, ERROR | Logs schema initialization |
| `upsert_object` | INFO, WARNING | Logs object upsert from Django models |
| `delete_object` | INFO, DEBUG, WARNING, ERROR | Logs object deletion |
| `upsert_instance` | DEBUG, WARNING | Logs Django instance upsert |
| `sync_project` | INFO | Logs project synchronization |
| `exists_instance` | DEBUG | Logs existence checks |
| `exists_object` | DEBUG | Logs object existence checks |
| `fetch_object` | DEBUG | Logs object fetching |
| `fetch_object_by_type` | DEBUG, ERROR | Logs object retrieval by type |

### Log Levels Strategy

#### INFO Level
- Used for major operations start and completion
- Examples:
  - "Upserting document: item:123 in project proj-1"
  - "Query completed: returned 5 results for 'login bug' in project proj-1"
  - "Starting sync for project proj-1"

#### DEBUG Level  
- Used for detailed operation tracking
- Internal state and intermediate results
- Examples:
  - "Upserted document: item:123 -> uuid-string"
  - "Checking existence of object: item:123"
  - "Fetching object by type: item:123"

#### WARNING Level
- Used for expected error conditions
- Non-critical issues that don't prevent operation
- Examples:
  - "Object not found: item:123"
  - "Could not serialize object: item:123"
  - "Could not delete item:123 (might not exist)"

#### ERROR Level
- Used for unexpected errors
- Includes full stack traces with `exc_info=True`
- Automatically sent to Sentry when configured
- Examples:
  - "Failed to upsert document item:123: ValueError: Invalid data"
  - "Query failed for 'login bug' in project proj-1: ConnectionError"
  - "Error deleting object item:123: WeaviateException"

## Logging Infrastructure (from Issue #400)

The logging infrastructure was already set up in `agira/settings.py`:

### Local File Logging
- **Directory**: `./logs/` (or `/logs` in production)
- **Filename**: `app.log` (current), `app.log.2026-02-05` (rotated)
- **Rotation**: Daily at midnight
- **Retention**: 7 days (via `backupCount=7`)
- **Format**: `[LEVEL] YYYY-MM-DD HH:MM:SS logger_name module.function: message`

### Console Logging
- **Level**: INFO and above
- **Format**: Simple format for readability

### Sentry Integration
- **Activation**: When `SENTRY_DSN` environment variable is set
- **Level**: ERROR only
- **Integration**: Django integration via sentry-sdk
- **Features**: Stack traces, environment context, error grouping

## Example Log Output

### INFO Level
```
[INFO] 2026-02-05 21:30:15 core.services.weaviate.service upsert_document: Upserting document: item:123 in project proj-1
[INFO] 2026-02-05 21:30:15 core.services.weaviate.service upsert_document: Successfully upserted document: item:123 -> abc-def-123
```

### DEBUG Level
```
[DEBUG] 2026-02-05 21:30:15 core.services.weaviate.service upsert_document: Upserted document: item:123 -> abc-def-123
[DEBUG] 2026-02-05 21:30:16 core.services.weaviate.service exists_object: Checking existence of object: item:123
```

### WARNING Level
```
[WARNING] 2026-02-05 21:30:20 core.services.weaviate.service upsert_object: Object not found: item:999
[WARNING] 2026-02-05 21:30:21 core.services.weaviate.service delete_document: Could not delete item:123 (might not exist)
```

### ERROR Level (sent to Sentry)
```
[ERROR] 2026-02-05 21:30:25 core.services.weaviate.service query: Query failed for 'login bug' in project proj-1: ConnectionError: Failed to connect
Traceback (most recent call last):
  File "core/services/weaviate/service.py", line 350, in query
    ...
ConnectionError: Failed to connect to Weaviate
```

## Testing

The logging integration can be tested by:

1. **Local Development**:
   ```bash
   # Logs will appear in ./logs/app.log
   python manage.py runserver
   ```

2. **With Sentry**:
   ```bash
   # Set Sentry DSN
   export SENTRY_DSN="https://your-dsn@sentry.io/project"
   python manage.py runserver
   # Errors will be sent to Sentry dashboard
   ```

3. **View Logs**:
   ```bash
   # Follow logs in real-time
   tail -f logs/app.log
   
   # Filter by level
   grep "\[ERROR\]" logs/app.log
   grep "\[INFO\]" logs/app.log
   ```

## Benefits

1. **Debugging**: Comprehensive DEBUG logs help trace issues in development
2. **Monitoring**: INFO logs provide operational visibility
3. **Error Tracking**: ERROR logs with stack traces sent to Sentry for production monitoring
4. **Audit Trail**: All operations logged with timestamps and context
5. **Performance**: Log rotation prevents disk space issues
6. **Compliance**: 7-day retention provides audit trail for recent operations

## Acceptance Criteria Met

✅ **Integrate logging in weaviate core Service**
- All major operations have logging

✅ **Log all messages (info, debug, warn, error)**
- INFO: 16 statements for major operations
- DEBUG: 11 statements for detailed tracking
- WARNING: 7 statements for expected errors
- ERROR: 10 statements for unexpected errors

✅ **Logging in local folder ./logs as defined in #400**
- Uses existing ./logs configuration from settings.py
- Daily rotation and 7-day retention

✅ **Log error to Sentry as defined in #400**
- ERROR-level logs sent to Sentry when SENTRY_DSN is configured
- Full stack traces included with exc_info=True

## Files Modified

- `core/services/weaviate/service.py` - Added comprehensive logging (44 log statements)

## Dependencies

No new dependencies added. Uses existing logging infrastructure:
- Python standard library `logging` module
- Django logging configuration from `agira/settings.py`
- Sentry SDK (already in requirements.txt from issue #400)
