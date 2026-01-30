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
    List all issues for a project (read-only).
    GET /embed/projects/<project_id>/issues/?token=...
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
    ).order_by('-updated_at')
    
    context = {
        'project': embed_access.project,
        'items': items,
        'organisation': embed_access.organisation,
        'token': token,
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
    
    context = {
        'project': embed_access.project,
        'organisation': embed_access.organisation,
        'item_types': item_types,
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
    
    # Validation
    if not title:
        return HttpResponse("Title is required", status=400)
    
    if len(title) > 500:
        return HttpResponse("Title must not exceed 500 characters", status=400)
    
    if not type_id:
        return HttpResponse("Type is required", status=400)
    
    try:
        item_type = ItemType.objects.get(id=type_id, is_active=True)
    except ItemType.DoesNotExist:
        return HttpResponse("Invalid item type", status=400)
    
    # Create the item
    with transaction.atomic():
        item = Item.objects.create(
            project=embed_access.project,
            organisation=embed_access.organisation,
            title=title,
            description=description,
            type=item_type,
            status=ItemStatus.INBOX,
            requester=None,  # External requester
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.created',
            target=item,
            actor=None,
            summary=f"Created via embed portal: {title}",
        )
    
    # Redirect to the issue detail page using reverse
    redirect_url = reverse('embed-issue-detail', args=[item.id]) + f'?token={token}'
    return redirect(redirect_url)


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
