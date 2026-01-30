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

from .models import (
    OrganisationEmbedProject, Project, Item, ItemComment, ItemType, 
    ItemStatus, CommentVisibility, CommentKind
)
from .services.activity import ActivityService


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
    GET /embed/projects/<project_id>/issues/?token=...&status=...&type=...&search=...&sort=...&order=...&page=...
    """
    token = request.GET.get('token')
    embed_access = validate_embed_token(token)
    
    if embed_access is None:
        return HttpResponseForbidden("Access disabled")
    
    # Verify the project_id matches the embed access
    if embed_access.project.id != project_id:
        raise Http404("Project not found")
    
    # Get all issues for this project
    items = Item.objects.filter(
        project=embed_access.project
    ).select_related(
        'type', 'assigned_to', 'requester'
    )
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    search_query = request.GET.get('search', '')
    sort_field = request.GET.get('sort', 'updated')
    sort_order = request.GET.get('order', 'desc')
    
    # Apply status filter
    if status_filter:
        items = items.filter(status=status_filter)
    
    # Apply type filter
    if type_filter:
        try:
            type_id = int(type_filter)
            items = items.filter(type_id=type_id)
        except (ValueError, TypeError):
            pass
    
    # Apply search
    if search_query:
        from django.db.models import Q
        items = items.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )
    
    # Apply sorting
    sort_mapping = {
        'id': 'id',
        'title': 'title',
        'status': 'status',
        'updated': 'updated_at',
    }
    
    sort_db_field = sort_mapping.get(sort_field, 'updated_at')
    if sort_order == 'asc':
        items = items.order_by(sort_db_field)
    else:
        items = items.order_by(f'-{sort_db_field}')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(items, 25)  # 25 items per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Get all item types for filter dropdown
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    
    # Get status choices
    status_choices = ItemStatus.choices
    
    context = {
        'project': embed_access.project,
        'items': page_obj,
        'page_obj': page_obj,
        'organisation': embed_access.organisation,
        'token': token,
        'item_types': item_types,
        'status_choices': status_choices,
        'current_status': status_filter,
        'current_type': type_filter,
        'current_search': search_query,
        'current_sort': sort_field,
        'current_order': sort_order,
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
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release'
        ).prefetch_related('nodes'),
        id=issue_id
    )
    
    # Security check: ensure item belongs to the embedded project
    if item.project.id != embed_access.project.id:
        raise Http404("Issue not found")
    
    # Get comments for this item (only public comments)
    comments = item.comments.select_related('author').filter(
        visibility=CommentVisibility.PUBLIC
    ).order_by('created_at')
    
    context = {
        'item': item,
        'comments': comments,
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
    from .models import User
    org_users = User.objects.filter(
        organisation=embed_access.organisation,
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
    from .models import User
    try:
        requester = User.objects.get(
            id=requester_id,
            organisation=embed_access.organisation,
            active=True
        )
    except User.DoesNotExist:
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
