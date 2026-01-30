# X-Frame-Options Fix for iframe Embedding

## Problem
The Customer Portal could not be embedded in an iframe from `https://app.ebner-vermietung.de/` due to the `X-Frame-Options: DENY` header set by Django's XFrameOptionsMiddleware.

Error message:
```
Refused to display 'https://agira.angermeier.net:8443/' in a frame because it set 'X-Frame-Options' to 'deny'.
```

## Solution
Created a custom middleware (`EmbedFrameMiddleware`) that:
1. Removes the `X-Frame-Options` header for embed endpoints (`/embed/*`)
2. Sets `Content-Security-Policy: frame-ancestors` header to allow specific domains
3. Preserves existing CSP directives to avoid security issues
4. Uses environment variable for configuration

## Technical Details

### Middleware Implementation
- Located in: `core/middleware.py`
- Class: `EmbedFrameMiddleware`
- Inherits from: `MiddlewareMixin`

### Configuration
The middleware is configured via environment variable:
```bash
EMBED_ALLOWED_ORIGINS=https://app.ebner-vermietung.de
```

Multiple domains can be specified (comma-separated):
```bash
EMBED_ALLOWED_ORIGINS=https://app.ebner-vermietung.de,https://example.com
```

Default value: `https://app.ebner-vermietung.de`

### Middleware Ordering
The middleware must be placed BEFORE `XFrameOptionsMiddleware` in `settings.py`:
```python
MIDDLEWARE = [
    # ... other middleware
    'core.middleware.EmbedFrameMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

This ordering is crucial because middleware `process_response` methods run in **reverse order**. By placing our middleware before XFrameOptionsMiddleware, its `process_response` runs AFTER XFrameOptionsMiddleware has set the header, allowing us to modify it.

### How It Works
1. For non-embed endpoints: Normal XFrameOptionsMiddleware behavior (X-Frame-Options: DENY)
2. For `/embed/*` endpoints:
   - XFrameOptionsMiddleware sets `X-Frame-Options: DENY`
   - EmbedFrameMiddleware removes the `X-Frame-Options` header
   - EmbedFrameMiddleware adds `Content-Security-Policy: frame-ancestors <domains>`
   - If CSP already exists, it preserves existing directives and appends frame-ancestors

### CSP Header Preservation
The middleware intelligently handles existing Content-Security-Policy headers:
- If no CSP exists: Sets `Content-Security-Policy: frame-ancestors <domains>`
- If CSP exists: Removes any existing `frame-ancestors` directive and appends the new one while preserving all other directives

Example:
```
Before: Content-Security-Policy: default-src 'self'; script-src 'self'
After:  Content-Security-Policy: default-src 'self'; script-src 'self'; frame-ancestors https://app.ebner-vermietung.de
```

## Standards Compliance
- Uses `Content-Security-Policy: frame-ancestors` (CSP Level 2)
- Modern browsers support this directive
- Replaces deprecated `X-Frame-Options: ALLOW-FROM` which is not supported by modern browsers

## Security Considerations
1. Only embed endpoints (`/embed/*`) are affected
2. All other endpoints retain `X-Frame-Options: DENY` protection
3. Specific domains must be whitelisted via environment variable
4. Existing CSP directives are preserved
5. Token-based authentication still required for embed endpoints

## Testing
Comprehensive tests added in `core/test_embed_frame_middleware.py`:
- Verifies X-Frame-Options removal for embed endpoints
- Verifies CSP frame-ancestors addition
- Verifies CSP header preservation
- Verifies non-embed endpoints remain protected
- Verifies configurable allowed origins

All 34 embed-related tests pass successfully.

## Deployment
1. Set `EMBED_ALLOWED_ORIGINS` environment variable in production
2. Restart the application to load the new middleware
3. Verify embedding works from the allowed domain

## References
- Django Issue: gdsanger/Agira#274
- Agira Item ID: 148
- CSP Specification: https://www.w3.org/TR/CSP2/#directive-frame-ancestors
