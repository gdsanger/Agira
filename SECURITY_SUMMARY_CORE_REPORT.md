# Security Summary - Core Report Service

## Overview

This document provides a security analysis of the Core Report Service implementation.

## Security Considerations

### 1. Input Validation ✅

**Context Data**
- Context is serialized to JSON, which provides basic sanitization
- No direct execution of user-provided code
- All template rendering is controlled by registered templates

**Risk**: LOW
**Mitigation**: Templates validate their own context data

### 2. File Storage 🔒

**PDF Files**
- Stored using Django's FileField with configurable storage backend
- Default upload path: `reports/%Y/%m/%d/`
- Filenames are generated with timestamp to prevent collisions

**Risk**: MEDIUM (if default storage is used without restrictions)
**Recommendations**:
- Configure private file storage (not publicly accessible)
- Implement access control for PDF downloads
- Set up file size limits
- Enable virus scanning for stored files

### 3. Code Execution ✅

**Template System**
- No dynamic code execution from user input
- Templates must be pre-registered in code
- ReportLab Platypus uses safe rendering

**Risk**: LOW
**Status**: Safe by design

### 4. Path Traversal ✅

**File Paths**
- Upload paths are controlled by Django
- No user-provided path components
- FileField handles sanitization

**Risk**: LOW
**Status**: Protected

### 5. Denial of Service

**Large PDFs**
- Multi-page reports can consume memory
- No built-in limits on report size

**Risk**: MEDIUM
**Recommendations**:
- Implement context size limits
- Add pagination for very large datasets
- Monitor memory usage
- Set timeout limits for PDF generation

### 6. Data Exposure

**Context Snapshots**
- Full context is stored in database as JSON
- May contain sensitive information

**Risk**: MEDIUM
**Recommendations**:
- Review context data before storing
- Implement data classification
- Consider encryption at rest for sensitive data
- Audit who can access ReportDocument records

### 7. Hash Integrity ✅

**SHA256 Hash**
- PDF integrity verification using SHA256
- Prevents tampering detection

**Risk**: LOW
**Status**: Implemented

## Implemented Security Measures

### ✅ What's Already Secure

1. **No SQL Injection**: Uses Django ORM exclusively
2. **No XSS**: PDFs don't execute JavaScript
3. **No CSRF**: No web forms in this component
4. **Input Sanitization**: JSON serialization
5. **Integrity Verification**: SHA256 hashing
6. **Audit Trail**: Created by and timestamp tracking

### 🔒 What Needs Additional Security

1. **Access Control**: Implement permission checks for:
   - Generating reports
   - Downloading stored reports
   - Viewing context snapshots

2. **File Storage**: Configure secure storage:
   ```python
   # settings.py
   STORAGES = {
       "default": {
           "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
           "OPTIONS": {
               "access_key": os.environ["AWS_ACCESS_KEY_ID"],
               "secret_key": os.environ["AWS_SECRET_ACCESS_KEY"],
               "bucket_name": "private-reports",
               "default_acl": "private",
           },
       },
   }
   ```

3. **Rate Limiting**: Add rate limits for report generation:
   ```python
   from django.views.decorators.ratelimit import ratelimit
   
   @ratelimit(key='user', rate='10/h')
   def generate_change_report(request, change_id):
       # ...
   ```

4. **Content Size Limits**: Implement validation:
   ```python
   MAX_CONTEXT_SIZE = 1_000_000  # 1MB JSON
   MAX_ITEMS_COUNT = 1000
   
   if len(json.dumps(context)) > MAX_CONTEXT_SIZE:
       raise ValueError("Context too large")
   ```

5. **Data Classification**: Add sensitivity markers:
   ```python
   class ReportDocument(models.Model):
       # ...
       sensitivity_level = models.CharField(
           max_length=20,
           choices=[
               ('PUBLIC', 'Public'),
               ('INTERNAL', 'Internal'),
               ('CONFIDENTIAL', 'Confidential'),
           ]
       )
   ```

## Recommended Security Enhancements

### Priority 1 (High)

1. **Implement Access Control**
   ```python
   from django.contrib.auth.decorators import permission_required
   
   @permission_required('core.view_reportdocument')
   def download_report(request, report_id):
       report = get_object_or_404(ReportDocument, id=report_id)
       # Check if user has access to the related object
       if not has_access(request.user, report.object_type, report.object_id):
           raise PermissionDenied
       return FileResponse(report.pdf_file)
   ```

2. **Configure Private Storage**
   - Use S3 with private ACLs or
   - Use local storage outside MEDIA_ROOT or
   - Implement custom storage backend with authentication

3. **Add Content Size Limits**
   ```python
   # core/services/reporting/service.py
   MAX_CONTEXT_SIZE = 1_000_000  # 1MB
   
   def generate_and_store(self, ...):
       context_json = json.dumps(context)
       if len(context_json) > MAX_CONTEXT_SIZE:
           raise ValueError(f"Context exceeds maximum size of {MAX_CONTEXT_SIZE} bytes")
       # ...
   ```

### Priority 2 (Medium)

1. **Add Rate Limiting**
   - Per user: 10-20 reports per hour
   - Per IP: 100 reports per hour

2. **Implement Audit Logging**
   ```python
   import logging
   
   audit_logger = logging.getLogger('security.audit')
   
   def generate_and_store(self, ...):
       # ...
       audit_logger.info(
           f"Report generated: {report_key} for {object_type}:{object_id} "
           f"by user {created_by.username if created_by else 'system'}"
       )
   ```

3. **Add Virus Scanning**
   - Scan generated PDFs before storage
   - Use ClamAV or cloud-based scanning

### Priority 3 (Low)

1. **Encrypt Sensitive Data**
   - Encrypt context_json for sensitive reports
   - Use Django's encryption fields

2. **Add Digital Signatures**
   - Sign PDFs for non-repudiation
   - Use PyPDF2 or reportlab.lib.pdfencrypt

3. **Implement Retention Policy**
   - Auto-delete old reports
   - Archive to cold storage

## Vulnerability Assessment

| Vulnerability | Risk Level | Status | Mitigation |
|--------------|------------|--------|------------|
| SQL Injection | LOW | ✅ Protected | Django ORM |
| XSS | LOW | ✅ N/A | PDF format |
| CSRF | LOW | ✅ N/A | No forms |
| Path Traversal | LOW | ✅ Protected | Django FileField |
| Code Injection | LOW | ✅ Protected | No dynamic code |
| DoS (Large PDFs) | MEDIUM | ⚠️ Partial | Add size limits |
| Unauthorized Access | MEDIUM | ⚠️ Needs work | Implement access control |
| Data Exposure | MEDIUM | ⚠️ Needs work | Review context data |
| File Storage | MEDIUM | ⚠️ Needs work | Use private storage |

## Compliance Considerations

### ISO 27001
- ✅ Audit trail implemented
- ✅ Integrity verification (SHA256)
- ⚠️ Need access control
- ⚠️ Need data classification

### GDPR
- ⚠️ Context may contain personal data
- ⚠️ Need data retention policy
- ⚠️ Need access logging
- ⚠️ Need right to deletion

## Security Checklist

Before deploying to production:

- [ ] Configure private file storage
- [ ] Implement access control
- [ ] Add rate limiting
- [ ] Set up audit logging
- [ ] Implement content size limits
- [ ] Review context data sensitivity
- [ ] Test permission boundaries
- [ ] Set up monitoring and alerts
- [ ] Document security procedures
- [ ] Train users on report handling

## Conclusion

The Core Report Service implementation has a solid security foundation with:
- No major vulnerabilities in core functionality
- Safe template system
- Integrity verification
- Audit trail

However, **access control and file storage security** must be implemented before production use, especially for sensitive reports.

The main security tasks are:
1. Implement permission-based access control
2. Configure private file storage
3. Add content size limits
4. Enable audit logging
5. Review data sensitivity

With these additions, the service will be production-ready and secure.
