"""
Embed views for external project portal access.

This module provides token-based access to a project's issues for external embedding via iFrame.
Access is controlled by OrganisationEmbedProject tokens.
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, Http404, HttpResponseForbidden
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta

from django_tables2 import RequestConfig

from .models import (
    OrganisationEmbedProject, Project, Item, ItemComment, ItemType, 
    ItemStatus, CommentVisibility, CommentKind, Attachment, AttachmentLink, AttachmentRole,
    Release
)
from .services.activity import ActivityService
from .services.storage import AttachmentStorageService
from .tables import EmbedItemTable
from .filters import EmbedItemFilter


# Constants for embed attachment uploads
MAX_ATTACHMENT_SIZE_MB = 10
MAX_ATTACHMENT_COUNT = 5
ALLOWED_ATTACHMENT_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.pdf', '.docx', '.md']


def validate_embed_token(token):
    """
    Validate embed token and return the OrganisationEmbedProject instance.
    
    Returns:
        OrganisationEmbedProject: The embed access object if valid and enabled
        None: If token is found but access is disabled (caller must return 403)
        
    Raises:
        Http404: If token is invalid or not found
    """
    if not token:
        raise Http404("Token not provided")
    
    try:
        embed_access = OrganisationEmbedProject.objects.select_related(
            'organisation', 'project'
        ).get(embed_token=token)
    except OrganisationEmbedProject.DoesNotExist:
        raise Http404("Invalid token")
    
    if not embed_access.is_enabled:
        # Return None for disabled access - caller must return 403 Forbidden
        return None
    
    return embed_access


def embed_project_issues(request, project_id):
    """
    List all issues for a project with filtering, search, sorting, and pagination.
    Uses django-tables2 and django-filter.
    GET /embed/projects/<project_id>/issues/?token=...&status=...&type=...&q=...
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Verify the project_id matches the embed access
    if embed_access.project.id != project_id:
        raise Http404("Project not found")
    
    # Get all issues for this project, excluding intern items (security requirement)
    queryset = Item.objects.filter(
        project=embed_access.project,
        intern=False  # Security: never show internal items in customer portal
    ).select_related(
        'type', 'assigned_to', 'requester', 'solution_release'
    )
    
    # Apply filters using django-filter
    filterset = EmbedItemFilter(request.GET, queryset=queryset)
    
    # Create table with filtered queryset
    table = EmbedItemTable(filterset.qs)
    table.token = token  # Pass token to table for URL generation
    
    # Configure table with pagination
    RequestConfig(request, paginate={'per_page': 25}).configure(table)
    
    # Calculate KPIs with a single optimized query (only non-internal items)
    from django.db.models import Q, Count, Case, When, IntegerField
    
    kpi_data = Item.objects.filter(
        project=embed_access.project,
        intern=False
    ).aggregate(
        open_count=Count('id', filter=~Q(status=ItemStatus.CLOSED)),
        closed_30d_count=Count(
            'id',
            filter=Q(status=ItemStatus.CLOSED, updated_at__gte=timezone.now() - timedelta(days=30))
        ),
        inbox_count=Count('id', filter=Q(status=ItemStatus.INBOX)),
        backlog_count=Count('id', filter=Q(status=ItemStatus.BACKLOG))
    )
    
    kpis = {
        'open_count': kpi_data['open_count'] or 0,
        'closed_30d_count': kpi_data['closed_30d_count'] or 0,
        'inbox_count': kpi_data['inbox_count'] or 0,
        'backlog_count': kpi_data['backlog_count'] or 0,
    }
    
    context = {
        'project': embed_access.project,
        'organisation': embed_access.organisation,
        'token': token,
        'table': table,
        'filter': filterset,
        'kpis': kpis,
        # Keep items for solution modals
        'items': filterset.qs,
    }
    return render(request, 'embed/issue_list.html', context)


def embed_issue_detail(request, issue_id):
    """
    Show issue details including comments (read-only).
    GET /embed/issues/<issue_id>/?token=...
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Get the issue and verify it belongs to the embedded project
    # Security: Exclude intern items
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release'
        ).prefetch_related('nodes').filter(intern=False),
        id=issue_id
    )
    
    # Security check: ensure item belongs to the embedded project
    if item.project.id != embed_access.project.id:
        raise Http404("Issue not found")
    
    # Get comments for this item (only public comments)
    comments = item.comments.select_related('author').filter(
        visibility=CommentVisibility.PUBLIC
    ).order_by('created_at')
    
    # Get attachments for this item
    content_type_obj = ContentType.objects.get_for_model(Item)
    attachment_links = AttachmentLink.objects.filter(
        target_content_type=content_type_obj,
        target_object_id=item.id,
        role=AttachmentRole.ITEM_FILE
    ).select_related('attachment')
    
    attachments = [link.attachment for link in attachment_links if not link.attachment.is_deleted]
    
    context = {
        'item': item,
        'comments': comments,
        'attachments': attachments,
        'project': embed_access.project,
        'organisation': embed_access.organisation,
        'token': token,
    }
    return render(request, 'embed/issue_detail.html', context)


def embed_issue_create_form(request, project_id):
    """
    Show the create issue form.
    GET /embed/projects/<project_id>/issues/create/?token=...
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Verify the project_id matches the embed access
    if embed_access.project.id != project_id:
        raise Http404("Project not found")
    
    # Get active item types for the form
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    
    # Get organization users for requester selection
    from .models import User, UserOrganisation
    org_user_ids = UserOrganisation.objects.filter(
        organisation=embed_access.organisation
    ).values_list('user_id', flat=True)
    
    org_users = User.objects.filter(
        id__in=org_user_ids,
        active=True
    ).order_by('name')
    
    context = {
        'project': embed_access.project,
        'organisation': embed_access.organisation,
        'item_types': item_types,
        'org_users': org_users,
        'token': token,
    }
    return render(request, 'embed/issue_create.html', context)


@csrf_exempt
@require_POST
def embed_attachment_pre_upload(request, project_id):
    """
    Pre-upload an attachment before issue creation.
    POST /embed/projects/<project_id>/attachments/pre-upload/?token=...
    
    This endpoint allows uploading attachments before creating an issue.
    The attachments are temporarily stored and will be linked to the issue upon creation.
    """
    import os
    
    token = request.POST.get('token') or request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Verify the project_id matches the embed access
    if embed_access.project.id != project_id:
        raise Http404("Project not found")
    
    # Get uploaded file
    if 'file' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No file provided'
        }, status=400)
    
    uploaded_file = request.FILES['file']
    is_inline = request.POST.get('is_inline', 'false').lower() == 'true'
    
    # Validate file type
    # Security: SVG and HTML files can contain JavaScript and pose XSS risks
    # Only allow safe file types for embed portal
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    
    if file_extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        return JsonResponse({
            'success': False,
            'error': f'File type not allowed. Allowed types: {", ".join(ALLOWED_ATTACHMENT_EXTENSIONS)}'
        }, status=400)
    
    # Validate file size
    max_size_bytes = MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
    if uploaded_file.size > max_size_bytes:
        return JsonResponse({
            'success': False,
            'error': f'File size exceeds maximum of {MAX_ATTACHMENT_SIZE_MB}MB'
        }, status=400)
    
    try:
        # Store attachment using the storage service with custom max size
        storage_service = AttachmentStorageService(max_size_mb=MAX_ATTACHMENT_SIZE_MB)
        
        # Create a temporary Item placeholder to store the attachment
        # We'll use the project as the temporary target and update the link later
        attachment = Attachment.objects.create(
            created_by=None,
            original_name=uploaded_file.name,
            content_type=uploaded_file.content_type or '',
            size_bytes=uploaded_file.size,
            sha256='',  # Will be computed if needed
            storage_path='',  # Will be set below
            is_deleted=False
        )
        
        # Build storage path for temporary attachment
        from core.services.storage.paths import build_attachment_path, get_absolute_path, sanitize_filename
        relative_path = build_attachment_path(embed_access.project, attachment.id, uploaded_file.name)
        absolute_path = get_absolute_path(storage_service.data_dir, relative_path)
        
        # Ensure parent directory exists
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file to storage
        with open(absolute_path, 'wb') as dest:
            uploaded_file.seek(0)
            # Write in chunks
            while chunk := uploaded_file.read(8192):
                dest.write(chunk)
        
        # Update attachment with storage path
        attachment.storage_path = relative_path
        attachment.save(update_fields=['storage_path'])
        
        # Generate URL for inline images
        attachment_url = ''
        if is_inline:
            # For inline images, we need to provide a URL that can be used in the markdown
            # We'll use the embed attachment download URL
            attachment_url = reverse('embed-attachment-download', args=[attachment.id]) + f'?token={token}'
        
        return JsonResponse({
            'success': True,
            'message': 'File uploaded successfully',
            'attachment_id': attachment.id,
            'filename': attachment.original_name,
            'url': attachment_url,
        })
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error pre-uploading attachment: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_POST
def embed_issue_create(request, project_id):
    """
    Create a new issue.
    POST /embed/projects/<project_id>/issues/create/?token=...
    """
    token = request.POST.get('token') or request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Verify the project_id matches the embed access
    if embed_access.project.id != project_id:
        raise Http404("Project not found")
    
    # Get form data
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    type_id = request.POST.get('type')
    requester_id = request.POST.get('requester')
    
    # Validation
    if not title:
        return HttpResponse("Title is required", status=400)
    
    if len(title) > 500:
        return HttpResponse("Title must not exceed 500 characters", status=400)
    
    if not type_id:
        return HttpResponse("Type is required", status=400)
    
    if not requester_id:
        return HttpResponse("Requester is required", status=400)
    
    try:
        item_type = ItemType.objects.get(id=type_id, is_active=True)
    except ItemType.DoesNotExist:
        return HttpResponse("Invalid item type", status=400)
    
    # Get requester user
    from .models import User, UserOrganisation
    try:
        # Verify requester exists and belongs to the organization
        user_org = UserOrganisation.objects.get(
            user_id=requester_id,
            organisation=embed_access.organisation
        )
        requester = user_org.user
        if not requester.active:
            return HttpResponse("Requester is not active", status=400)
    except UserOrganisation.DoesNotExist:
        return HttpResponse("Invalid requester", status=400)
    
    # Create the item
    with transaction.atomic():
        item = Item.objects.create(
            project=embed_access.project,
            organisation=embed_access.organisation,
            title=title,
            description=description,
            type=item_type,
            status=ItemStatus.INBOX,
            requester=requester,
        )
        
        # Link pre-uploaded attachments to the item
        attachment_ids_str = request.POST.get('attachment_ids', '').strip()
        if attachment_ids_str:
            try:
                attachment_ids = [int(aid) for aid in attachment_ids_str.split(',') if aid.strip().isdigit()]
            except (ValueError, AttributeError):
                # Log warning but don't fail the creation
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Invalid attachment IDs format when creating item: {attachment_ids_str}")
                attachment_ids = []
            
            # Get the attachments and link them to the item
            content_type_obj = ContentType.objects.get_for_model(Item)
            for attachment_id in attachment_ids:
                try:
                    attachment = Attachment.objects.get(id=attachment_id)
                    
                    # Create attachment link
                    AttachmentLink.objects.create(
                        attachment=attachment,
                        target_content_type=content_type_obj,
                        target_object_id=item.id,
                        role=AttachmentRole.ITEM_FILE
                    )
                except Attachment.DoesNotExist:
                    # Log warning but don't fail the creation
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Attachment {attachment_id} not found when creating item {item.id}")
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.created',
            target=item,
            actor=None,
            summary=f"Created via embed portal: {title}",
        )
        
        # Send confirmation email to requester
        _send_requester_confirmation_email(item, requester)
    
    # Redirect to the issue detail page using reverse
    redirect_url = reverse('embed-issue-detail', args=[item.id]) + f'?token={token}'
    return redirect(redirect_url)


def _send_requester_confirmation_email(item, requester):
    """
    Send confirmation email to requester using activity-assigned template.
    
    Args:
        item: Created Item instance
        requester: User who requested the item
    """
    from .models import MailTemplate
    from .services.mail.template_processor import process_template
    from .services.graph.client import get_client
    from .services.exceptions import ServiceDisabled, ServiceNotConfigured, ServiceError
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        # Get the activity-assigned template
        template = MailTemplate.objects.get(key='activity-assigned')
        
        # Process template with item data
        processed = process_template(template, item)
        
        # Prepare email payload for Graph API
        payload = {
            "message": {
                "subject": processed['subject'],
                "body": {
                    "contentType": "HTML",
                    "content": processed['message']
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": requester.email
                        }
                    }
                ]
            },
            "saveToSentItems": True
        }
        
        # Add CC if specified in template
        if template.cc_address:
            cc_addresses = [addr.strip() for addr in template.cc_address.split(',') if addr.strip()]
            if cc_addresses:
                payload["message"]["ccRecipients"] = [
                    {"emailAddress": {"address": addr}} for addr in cc_addresses
                ]
        
        # Send email via Graph API
        client = get_client()
        sender_upn = template.from_address if template.from_address else requester.email
        client.send_mail(sender_upn, payload)
        
        logger.info(f"Sent confirmation email to requester {requester.email} for item {item.id}")
        
    except MailTemplate.DoesNotExist:
        logger.warning(f"activity-assigned template not found, skipping email for item {item.id}")
    except (ServiceDisabled, ServiceNotConfigured) as e:
        logger.warning(f"Email service not configured, skipping email for item {item.id}: {e}")
    except ServiceError as e:
        logger.error(f"Failed to send confirmation email for item {item.id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending confirmation email for item {item.id}: {e}")


@csrf_exempt
@require_POST
def embed_issue_add_comment(request, issue_id):
    """
    Add a comment to an issue.
    POST /embed/issues/<issue_id>/comments/?token=...
    """
    token = request.POST.get('token') or request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Get the issue and verify it belongs to the embedded project
    item = get_object_or_404(Item, id=issue_id)
    
    # Security check: ensure item belongs to the embedded project
    if item.project.id != embed_access.project.id:
        raise Http404("Issue not found")
    
    # Get comment body
    body = request.POST.get('body', '').strip()
    
    if not body:
        return HttpResponse("Comment body cannot be empty", status=400)
    
    # Create comment (marked as public and external)
    with transaction.atomic():
        comment = ItemComment.objects.create(
            item=item,
            author=None,  # External commenter
            body=body,
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.COMMENT,
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='comment.added',
            target=item,
            actor=None,
            summary=f"Added comment via embed portal",
        )
    
    # Redirect back to issue detail using reverse
    redirect_url = reverse('embed-issue-detail', args=[issue_id]) + f'?token={token}'
    return redirect(redirect_url)


@csrf_exempt
@require_POST
def embed_issue_upload_attachment(request, issue_id):
    """
    Upload an attachment to an issue via the embed portal.
    POST /embed/issues/<issue_id>/upload-attachment/?token=...
    """
    token = request.POST.get('token') or request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Get the issue and verify it belongs to the embedded project
    item = get_object_or_404(Item, id=issue_id)
    
    # Security check: ensure item belongs to the embedded project
    if item.project.id != embed_access.project.id:
        raise Http404("Issue not found")
    
    # Get uploaded file
    if 'file' not in request.FILES:
        return HttpResponse("No file provided", status=400)
    
    uploaded_file = request.FILES['file']
    
    try:
        # Store attachment using the storage service
        storage_service = AttachmentStorageService()
        attachment = storage_service.store_attachment(
            file=uploaded_file,
            target=item,
            role=AttachmentRole.ITEM_FILE,
            created_by=None,  # Anonymous upload from embed portal
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='attachment.uploaded',
            target=item,
            actor=None,
            summary=f"File uploaded via embed portal: {uploaded_file.name}",
        )
        
        # Return success response (for AJAX)
        return JsonResponse({
            'success': True,
            'message': 'File uploaded successfully',
            'attachment_id': attachment.id,
            'filename': attachment.original_name,
        })
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error uploading attachment to item {issue_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def embed_issue_attachments(request, issue_id):
    """
    Get attachments list for an issue (for HTMX refresh).
    GET /embed/issues/<issue_id>/attachments/?token=...
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Get the issue and verify it belongs to the embedded project
    item = get_object_or_404(Item, id=issue_id)
    
    # Security check: ensure item belongs to the embedded project
    if item.project.id != embed_access.project.id:
        raise Http404("Issue not found")
    
    # Get attachments for this item
    content_type = ContentType.objects.get_for_model(Item)
    attachment_links = AttachmentLink.objects.filter(
        target_content_type=content_type,
        target_object_id=item.id,
        role=AttachmentRole.ITEM_FILE
    ).select_related('attachment')
    
    attachments = [link.attachment for link in attachment_links if not link.attachment.is_deleted]
    
    return render(request, 'embed/partials/attachments_list.html', {
        'attachments': attachments,
    })


def embed_project_releases(request, project_id):
    """
    List all releases for a project with their associated items.
    GET /embed/projects/<project_id>/releases/?token=...
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Verify the project_id matches the embed access
    if embed_access.project.id != project_id:
        raise Http404("Project not found")
    
    # Get all releases for this project with prefetched items to avoid N+1 queries
    # Only fetch non-internal items
    from django.db.models import Prefetch
    
    releases = Release.objects.filter(
        project=embed_access.project
    ).prefetch_related(
        Prefetch(
            'items',
            queryset=Item.objects.filter(intern=False).select_related('type').order_by('-updated_at'),
            to_attr='filtered_items'
        )
    ).order_by('-update_date', '-id')
    
    # Build releases with their filtered items
    releases_with_items = []
    for release in releases:
        releases_with_items.append({
            'release': release,
            'items': release.filtered_items,  # Use prefetched filtered items
        })
    
    context = {
        'project': embed_access.project,
        'organisation': embed_access.organisation,
        'token': token,
        'releases_with_items': releases_with_items,
    }
    return render(request, 'embed/releases.html', context)


def embed_attachment_download(request, attachment_id):
    """
    Download an attachment via the embed portal.
    GET /embed/attachments/<attachment_id>/download/?token=...
    
    This endpoint allows downloading attachments through the embed portal.
    Validates the token to ensure the requester has access to the project.
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        if attachment.is_deleted:
            raise Http404("Attachment not found")
        
        # Verify that the attachment belongs to an item in the embedded project
        # or is a pre-uploaded attachment (no links yet)
        attachment_links = AttachmentLink.objects.filter(attachment=attachment)
        
        if attachment_links.exists():
            # Check if any link is to an item in the embedded project
            item_content_type = ContentType.objects.get_for_model(Item)
            valid_link = False
            
            for link in attachment_links:
                if link.target_content_type == item_content_type:
                    item = Item.objects.filter(id=link.target_object_id, project=embed_access.project).first()
                    if item:
                        valid_link = True
                        break
            
            if not valid_link:
                raise Http404("Attachment not found")
        
        # Read file content
        storage_service = AttachmentStorageService()
        file_content = storage_service.read_attachment(attachment)
        
        # Determine if this is an image for inline display
        content_type = attachment.content_type or 'application/octet-stream'
        is_image = content_type.startswith('image/')
        
        # Sanitize filename for header (prevent header injection)
        from urllib.parse import quote
        safe_filename = quote(attachment.original_name)
        
        # Create response with file
        response = HttpResponse(file_content, content_type=content_type)
        
        if is_image:
            # For images, display inline
            response['Content-Disposition'] = f'inline; filename="{safe_filename}"'
        else:
            # For other files, force download
            response['Content-Disposition'] = f'attachment; filename="{safe_filename}"'
        
        response['Content-Length'] = len(file_content)
        
        return response
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Download failed for attachment {attachment_id}: {e}")
        return HttpResponse(f"Download failed: {str(e)}", status=500)
