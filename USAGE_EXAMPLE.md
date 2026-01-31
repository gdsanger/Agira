# Core Report Service - Usage Example

## Quick Start

This guide shows how to integrate the Core Report Service into your views and business logic.

## Example 1: Generate Change Report in a View

```python
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required

from core.models import Change, Item
from core.services.reporting import ReportService


@login_required
def generate_change_report(request, change_id):
    """
    Generate a PDF report for a change.
    Downloads the PDF directly to the user.
    """
    # Get the change
    change = get_object_or_404(Change, id=change_id)
    
    # Build context from model
    context = {
        'title': change.title,
        'project_name': change.project.name,
        'description': change.description,
        'status': change.get_status_display(),
        'risk': change.get_risk_display(),
        'planned_start': change.planned_start.strftime('%Y-%m-%d %H:%M') if change.planned_start else 'N/A',
        'planned_end': change.planned_end.strftime('%Y-%m-%d %H:%M') if change.planned_end else 'N/A',
        'executed_at': change.executed_at.strftime('%Y-%m-%d %H:%M') if change.executed_at else 'N/A',
        'risk_description': change.risk_description,
        'mitigation': change.mitigation,
        'rollback_plan': change.rollback_plan,
        'communication_plan': change.communication_plan,
        'created_by': change.created_by.name if change.created_by else 'N/A',
        'created_at': change.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        
        # Related items
        'items': [
            {
                'title': item.title,
                'status': item.get_status_display()
            }
            for item in change.items.all()
        ],
        
        # Approvals
        'approvals': [
            {
                'approver': approval.approver.name,
                'status': approval.get_status_display(),
                'decision_at': approval.decision_at.strftime('%Y-%m-%d') if approval.decision_at else 'N/A'
            }
            for approval in change.approvals.all()
        ]
    }
    
    # Generate PDF
    service = ReportService()
    pdf_bytes = service.render('change.v1', context)
    
    # Return as download
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="change_{change.id}_report.pdf"'
    return response
```

## Example 2: Generate and Store Report

```python
from django.shortcuts import redirect
from django.contrib import messages
from core.services.reporting import ReportService


@login_required
def generate_and_archive_report(request, change_id):
    """
    Generate a PDF report and store it in the database.
    Redirects to the change detail page.
    """
    change = get_object_or_404(Change, id=change_id)
    
    # Build context (same as Example 1)
    context = {
        # ... context data ...
    }
    
    # Generate and store with metadata
    service = ReportService()
    report = service.generate_and_store(
        report_key='change.v1',
        object_type='change',
        object_id=change.id,
        context=context,
        created_by=request.user,
        metadata={
            'template_version': '1.0',
            'generated_from_view': 'change_detail'
        }
    )
    
    messages.success(request, f'Report generated and archived. Report ID: {report.id}')
    return redirect('change_detail', change_id=change.id)
```

## Example 3: List All Reports for a Change

```python
from django.shortcuts import render
from core.models import ReportDocument


@login_required
def list_change_reports(request, change_id):
    """
    Show all generated reports for a change.
    """
    change = get_object_or_404(Change, id=change_id)
    
    # Query all reports for this change
    reports = ReportDocument.objects.filter(
        object_type='change',
        object_id=str(change.id)
    )
    
    return render(request, 'reports/list.html', {
        'change': change,
        'reports': reports
    })
```

## Example 4: Download Archived Report

```python
from django.http import FileResponse


@login_required
def download_archived_report(request, report_id):
    """
    Download a previously generated and archived report.
    """
    report = get_object_or_404(ReportDocument, id=report_id)
    
    # Check permissions (example)
    # if not request.user.has_perm('view_report', report):
    #     return HttpResponseForbidden()
    
    # Return the stored PDF
    response = FileResponse(
        report.pdf_file.open('rb'),
        content_type='application/pdf'
    )
    response['Content-Disposition'] = f'attachment; filename="{report.report_key}_{report.object_id}.pdf"'
    return response
```

## Example 5: Background Task with Celery (Optional)

```python
from celery import shared_task
from core.models import Change, User
from core.services.reporting import ReportService


@shared_task
def generate_change_report_async(change_id, user_id):
    """
    Generate a change report asynchronously.
    """
    change = Change.objects.get(id=change_id)
    user = User.objects.get(id=user_id)
    
    context = {
        # ... build context ...
    }
    
    service = ReportService()
    report = service.generate_and_store(
        report_key='change.v1',
        object_type='change',
        object_id=change.id,
        context=context,
        created_by=user
    )
    
    # Send notification email with link
    send_mail(
        subject=f'Report ready: {change.title}',
        message=f'Your report is ready. Report ID: {report.id}',
        from_email='noreply@example.com',
        recipient_list=[user.email]
    )
    
    return report.id


# In your view:
def request_change_report(request, change_id):
    generate_change_report_async.delay(change_id, request.user.id)
    messages.info(request, 'Report generation started. You will receive an email when ready.')
    return redirect('change_detail', change_id=change_id)
```

## URLs Configuration

```python
from django.urls import path
from . import views

urlpatterns = [
    path('change/<int:change_id>/report/', views.generate_change_report, name='generate_change_report'),
    path('change/<int:change_id>/report/archive/', views.generate_and_archive_report, name='archive_change_report'),
    path('change/<int:change_id>/reports/', views.list_change_reports, name='list_change_reports'),
    path('report/<int:report_id>/download/', views.download_archived_report, name='download_report'),
]
```

## Template Example

```html
<!-- reports/list.html -->
{% extends "base.html" %}

{% block content %}
<h1>Reports for {{ change.title }}</h1>

<table class="table">
    <thead>
        <tr>
            <th>Report Type</th>
            <th>Created At</th>
            <th>Created By</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for report in reports %}
        <tr>
            <td>{{ report.report_key }}</td>
            <td>{{ report.created_at|date:"Y-m-d H:i" }}</td>
            <td>{{ report.created_by.name }}</td>
            <td>
                <a href="{% url 'download_report' report.id %}" class="btn btn-sm btn-primary">
                    Download PDF
                </a>
            </td>
        </tr>
        {% empty %}
        <tr>
            <td colspan="4">No reports generated yet.</td>
        </tr>
        {% endfor %}
    </tbody>
</table>

<a href="{% url 'archive_change_report' change.id %}" class="btn btn-success">
    Generate New Report
</a>
{% endblock %}
```

## Admin Integration

```python
# admin.py
from django.contrib import admin
from core.models import ReportDocument


@admin.register(ReportDocument)
class ReportDocumentAdmin(admin.ModelAdmin):
    list_display = ['report_key', 'object_type', 'object_id', 'created_at', 'created_by']
    list_filter = ['report_key', 'object_type', 'created_at']
    search_fields = ['object_id', 'created_by__username']
    readonly_fields = ['created_at', 'sha256', 'context_json']
    
    def has_add_permission(self, request):
        # Reports should only be generated programmatically
        return False
```

## Best Practices

1. **Always use context snapshots**: Don't pass model instances directly
2. **Validate context**: Ensure all required fields are present
3. **Handle missing data**: Use defaults like 'N/A' for optional fields
4. **Test with real data**: Use production-like data for testing
5. **Monitor file storage**: Ensure adequate disk space for PDFs
6. **Set up backups**: Include report files in backup strategy
7. **Clean old reports**: Implement retention policy if needed

## Error Handling

```python
from core.services.reporting import ReportService


try:
    service = ReportService()
    pdf_bytes = service.render('change.v1', context)
except KeyError as e:
    # Report template not found
    messages.error(request, f'Report template not available: {e}')
    return redirect('change_detail', change_id=change.id)
except Exception as e:
    # Other errors during generation
    logger.exception('Error generating report')
    messages.error(request, 'Failed to generate report. Please try again.')
    return redirect('change_detail', change_id=change.id)
```

## Testing Integration

```python
from django.test import TestCase
from core.models import Change, Project, User
from core.services.reporting import ReportService


class ChangeReportIntegrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='test', email='test@example.com')
        self.project = Project.objects.create(name='Test Project')
        self.change = Change.objects.create(
            project=self.project,
            title='Test Change',
            created_by=self.user
        )
    
    def test_generate_report_for_change(self):
        """Test generating report from a real Change object"""
        context = {
            'title': self.change.title,
            'project_name': self.project.name,
            # ... more fields
        }
        
        service = ReportService()
        report = service.generate_and_store(
            report_key='change.v1',
            object_type='change',
            object_id=self.change.id,
            context=context,
            created_by=self.user
        )
        
        self.assertIsNotNone(report.pdf_file)
        self.assertEqual(report.object_type, 'change')
        self.assertEqual(int(report.object_id), self.change.id)
```
