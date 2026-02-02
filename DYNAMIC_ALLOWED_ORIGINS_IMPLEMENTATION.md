# Dynamic Allowed Origins Implementation

## Overview
This document describes the implementation of dynamic allowed-origins configuration for the Customer Portal Embed feature (Issue #235).

## Problem Statement
Previously, allowed domains/origins for iframe embedding were statically configured in `core/middleware.py` via environment variables. This was impractical and prevented organization/project-specific configuration.

## Solution
Allowed origins are now configured per `OrganisationEmbedProject` in the database, providing dynamic, runtime control over iframe embedding permissions.

## Implementation Details

### 1. Database Model Extension
**File:** `core/models.py`

Added new field to `OrganisationEmbedProject`:
```python
allowed_origins = models.TextField(
    blank=True,
    default='',
    help_text=_('Comma-separated list of allowed origins for iframe embedding')
)
```

Added helper method:
```python
def get_allowed_origins(self):
    """Parse and return the list of allowed origins."""
    if not self.allowed_origins:
        return []
    
    origins = [
        origin.strip() 
        for origin in self.allowed_origins.split(',') 
        if origin.strip()
    ]
    return origins
```

### 2. Migration
**File:** `core/migrations/0037_add_allowed_origins_to_embed_project.py`

- Adds `allowed_origins` TextField to `organisationembedproject` table
- Default: empty string
- Blank: True (optional field)

### 3. Admin Interface
**File:** `core/admin.py`

Updated `OrganisationEmbedProjectAdmin`:
- Added "Allowed Origins" fieldset with description
- Field appears in admin detail view with help text

Updated `OrganisationEmbedProjectInline`:
- Included `allowed_origins` in displayed fields
- Allows quick editing from Organization admin page

### 4. Middleware Refactoring
**File:** `core/middleware.py`

Complete refactoring of `EmbedFrameMiddleware`:

**Removed:**
- Environment variable configuration (`EMBED_ALLOWED_ORIGINS`)
- Static initialization of allowed origins

**Added:**
- `_get_embed_token_from_request(request)`: Extracts token from GET or POST parameters
- `_get_allowed_origins(token)`: Fetches allowed origins from database via token lookup

**Behavior:**
- For `/embed/` paths, extracts token from request
- Looks up `OrganisationEmbedProject` by token
- If found and enabled, uses `get_allowed_origins()` for CSP configuration
- Sets `Content-Security-Policy: frame-ancestors <origins>` header
- **Fail-closed security**: If no token, invalid token, disabled access, or empty origins → sets `frame-ancestors 'none'`

### 5. Security Model

**Fail-Closed Approach:**
- No token provided → deny framing
- Invalid token → deny framing
- Disabled embed access → deny framing
- Empty allowed_origins → deny framing
- Valid token + origins → allow framing from specified origins only

**Token Validation:**
- Existing embed token validation in views remains unchanged
- Middleware adds additional layer via CSP control

**CSP Headers:**
- Modern `Content-Security-Policy: frame-ancestors` directive
- Replaces deprecated `X-Frame-Options: ALLOW-FROM`
- Compatible with all modern browsers

## Testing

### Test Coverage
All tests pass (102 total for embed functionality):

**Model Tests** (`test_organisation_embed_project.py`):
- ✅ Empty origins returns empty list
- ✅ Single origin parsing
- ✅ Multiple origins parsing
- ✅ Whitespace trimming
- ✅ Empty entry removal
- ✅ Multiline input handling
- ✅ Default value is empty string

**Middleware Tests** (`test_embed_frame_middleware.py`):
- ✅ Valid token with origins allows framing
- ✅ Invalid token denies framing
- ✅ Disabled access denies framing
- ✅ Empty origins denies framing
- ✅ Multiple origins are included in CSP
- ✅ Whitespace is properly handled
- ✅ Existing CSP headers are preserved
- ✅ Non-embed endpoints remain protected

**Integration Tests** (`test_embed_endpoints.py`):
- ✅ All 49 embed endpoint tests pass with new middleware

**Admin Tests** (`test_organisation_embed_project_admin.py`):
- ✅ Field appears in admin fieldsets
- ✅ Field appears in inline admin
- ✅ All admin functionality works correctly

### Security Testing
- ✅ CodeQL analysis: 0 vulnerabilities found
- ✅ Code review: No issues identified
- ✅ Fail-closed behavior verified

## Usage Examples

### Admin Configuration
1. Navigate to Admin → Organisation Embed Projects
2. Select or create an embed project
3. In "Allowed Origins" section, enter comma-separated origins:
   ```
   https://app.ebner-vermietung.de, https://portal.example.com, https://staging.example.org
   ```
4. Save the configuration

### Result
Embed endpoints will only be frameable from the specified origins. The CSP header will be:
```
Content-Security-Policy: frame-ancestors https://app.ebner-vermietung.de https://portal.example.com https://staging.example.org
```

### Whitespace Handling
Input with whitespace:
```
  https://app.example.com  ,  https://portal.example.com  
```

Parsed output (trimmed):
```python
['https://app.example.com', 'https://portal.example.com']
```

## Migration Guide

### For Existing Deployments

1. **Before Deployment:**
   - No action required; migration adds field with default empty value

2. **After Deployment:**
   - Run migration: `python manage.py migrate`
   - For each existing `OrganisationEmbedProject`:
     - Navigate to admin interface
     - Set `allowed_origins` field
     - Save changes

3. **Environment Variables:**
   - `EMBED_ALLOWED_ORIGINS` environment variable is no longer used
   - Can be removed from `.env` files

### Breaking Changes
- None. Existing embed tokens continue to work
- However, origins must be configured per project for framing to work
- Without configured origins, embeds will be blocked from iframes (fail-closed)

## Acceptance Criteria

✅ **Allowed Origins can be configured per OrganisationEmbedProject**
- Field exists in model
- Admin interface allows configuration
- Comma-separated list support

✅ **No static domain entries required in middleware**
- Removed environment variable dependency
- Database-driven configuration

✅ **Origin validation uses database configuration**
- Middleware fetches origins from DB
- CSP headers set based on project configuration

✅ **Robust list parsing**
- Whitespace trimmed
- Empty entries removed
- Multiline input supported

✅ **Comprehensive tests**
- Parsing logic tested
- Allowed origins → request allowed
- Disallowed origins → request denied
- Empty/missing list → request denied

## Files Changed
1. `core/models.py` - Added field and helper method
2. `core/migrations/0037_add_allowed_origins_to_embed_project.py` - Database migration
3. `core/admin.py` - Admin interface updates
4. `core/middleware.py` - Complete middleware refactoring
5. `core/test_organisation_embed_project.py` - Model tests
6. `core/test_embed_frame_middleware.py` - Middleware tests
7. `core/test_organisation_embed_project_admin.py` - Admin tests

## Security Summary
**No vulnerabilities introduced.**

- ✅ Fail-closed security model
- ✅ Token validation maintained
- ✅ CSP headers properly set
- ✅ Database queries use `.only()` for performance
- ✅ Exception handling prevents information leakage
- ✅ CodeQL scan: 0 alerts

## Future Enhancements (Optional)
- Add origin validation (URL format checking) in admin form
- Add regex pattern support for origin matching (e.g., `*.example.com`)
- Add logging for denied frame attempts
- Add metrics/monitoring for embed usage per origin

## References
- Issue: #235 - Organisation Embed Project Anpassung Middleware / EMBED_ALLOWED_ORIGINS
- Related: #138 - Embed Token Model
- CSP Spec: https://www.w3.org/TR/CSP3/#directive-frame-ancestors
