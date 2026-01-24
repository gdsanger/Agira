from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from .models import (
    Project, Item, ItemStatus, ItemComment, User, 
    Attachment, AttachmentLink, AttachmentRole, Activity
)
from .services.workflow import ItemWorkflowGuard
from .services.activity import ActivityService
from .services.storage import AttachmentStorageService

def home(request):
    """Home page view."""
    return render(request, 'home.html')

def dashboard(request):
    """Dashboard page view."""
    return render(request, 'dashboard.html')

def projects(request):
    """Projects page view."""
    projects_list = Project.objects.all()
    
    # Server-side search filter
    q = request.GET.get('q', '')
    if q:
        projects_list = projects_list.filter(name__icontains=q)
    
    context = {
        'projects': projects_list,
        'search_query': q,
    }
    return render(request, 'projects.html', context)

def project_detail(request, id):
    """Project detail page view."""
    project = get_object_or_404(Project, id=id)
    context = {
        'project': project,
    }
    return render(request, 'project_detail.html', context)

def items_inbox(request):
    """Items Inbox page view."""
    items = Item.objects.filter(status=ItemStatus.INBOX).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-created_at')
    
    context = {
        'items': items,
    }
    return render(request, 'items_inbox.html', context)

def items_backlog(request):
    """Items Backlog page view."""
    items = Item.objects.filter(status=ItemStatus.BACKLOG).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-updated_at')
    
    # Search filter
    q = request.GET.get('q', '')
    if q:
        items = items.filter(
            models.Q(title__icontains=q) | models.Q(description__icontains=q)
        )
    
    # Project filter
    project_id = request.GET.get('project', '')
    if project_id:
        try:
            items = items.filter(project_id=int(project_id))
        except (ValueError, TypeError):
            # Invalid project_id, ignore filter
            project_id = ''
    
    # Get all projects for filter dropdown
    projects = Project.objects.all().order_by('name')
    
    context = {
        'items': items,
        'search_query': q,
        'project_id': project_id,
        'projects': projects,
    }
    return render(request, 'items_backlog.html', context)

def items_working(request):
    """Items Working page view."""
    items = Item.objects.filter(status=ItemStatus.WORKING).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-updated_at')
    
    # Search filter
    q = request.GET.get('q', '')
    if q:
        items = items.filter(
            models.Q(title__icontains=q) | models.Q(description__icontains=q)
        )
    
    # Project filter
    project_id = request.GET.get('project', '')
    if project_id:
        try:
            items = items.filter(project_id=int(project_id))
        except (ValueError, TypeError):
            # Invalid project_id, ignore filter
            project_id = ''
    
    # Get all projects for filter dropdown
    projects = Project.objects.all().order_by('name')
    
    context = {
        'items': items,
        'search_query': q,
        'project_id': project_id,
        'projects': projects,
    }
    return render(request, 'items_working.html', context)

def items_testing(request):
    """Items Testing page view."""
    items = Item.objects.filter(status=ItemStatus.TESTING).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-updated_at')
    
    # Search filter
    q = request.GET.get('q', '')
    if q:
        items = items.filter(
            models.Q(title__icontains=q) | models.Q(description__icontains=q)
        )
    
    # Project filter
    project_id = request.GET.get('project', '')
    if project_id:
        try:
            items = items.filter(project_id=int(project_id))
        except (ValueError, TypeError):
            # Invalid project_id, ignore filter
            project_id = ''
    
    # Get all projects for filter dropdown
    projects = Project.objects.all().order_by('name')
    
    context = {
        'items': items,
        'search_query': q,
        'project_id': project_id,
        'projects': projects,
    }
    return render(request, 'items_testing.html', context)

def items_ready(request):
    """Items Ready for Release page view."""
    items = Item.objects.filter(status=ItemStatus.READY_FOR_RELEASE).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-updated_at')
    
    # Search filter
    q = request.GET.get('q', '')
    if q:
        items = items.filter(
            models.Q(title__icontains=q) | models.Q(description__icontains=q)
        )
    
    # Project filter
    project_id = request.GET.get('project', '')
    if project_id:
        try:
            items = items.filter(project_id=int(project_id))
        except (ValueError, TypeError):
            # Invalid project_id, ignore filter
            project_id = ''
    
    # Get all projects for filter dropdown
    projects = Project.objects.all().order_by('name')
    
    context = {
        'items': items,
        'search_query': q,
        'project_id': project_id,
        'projects': projects,
    }
    return render(request, 'items_ready.html', context)

def changes(request):
    """Changes page view."""
    return render(request, 'changes.html')

def item_detail(request, item_id):
    """Item detail page with tabs."""
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release'
        ),
        id=item_id
    )
    
    # Get initial tab from query parameter (default: overview)
    active_tab = request.GET.get('tab', 'overview')
    
    context = {
        'item': item,
        'active_tab': active_tab,
        'available_statuses': ItemStatus.choices,
    }
    return render(request, 'item_detail.html', context)


def item_comments_tab(request, item_id):
    """HTMX endpoint to load comments tab."""
    item = get_object_or_404(Item, id=item_id)
    comments = item.comments.select_related('author').order_by('created_at')
    
    context = {
        'item': item,
        'comments': comments,
    }
    return render(request, 'partials/item_comments_tab.html', context)


def item_attachments_tab(request, item_id):
    """HTMX endpoint to load attachments tab."""
    item = get_object_or_404(Item, id=item_id)
    
    # Get attachments linked to this item
    content_type = ContentType.objects.get_for_model(Item)
    attachment_links = AttachmentLink.objects.filter(
        target_content_type=content_type,
        target_object_id=item.id,
        role=AttachmentRole.ITEM_FILE
    ).select_related('attachment', 'attachment__created_by').order_by('-created_at')
    
    attachments = [link.attachment for link in attachment_links if not link.attachment.is_deleted]
    
    context = {
        'item': item,
        'attachments': attachments,
    }
    return render(request, 'partials/item_attachments_tab.html', context)


def item_activity_tab(request, item_id):
    """HTMX endpoint to load activity tab."""
    item = get_object_or_404(Item, id=item_id)
    
    # Get activities for this item
    activity_service = ActivityService()
    activities = activity_service.latest(limit=100, item=item)
    
    context = {
        'item': item,
        'activities': activities,
    }
    return render(request, 'partials/item_activity_tab.html', context)


def item_github_tab(request, item_id):
    """HTMX endpoint to load GitHub tab."""
    item = get_object_or_404(Item, id=item_id)
    external_mappings = item.external_mappings.all().order_by('-last_synced_at')
    
    context = {
        'item': item,
        'external_mappings': external_mappings,
    }
    return render(request, 'partials/item_github_tab.html', context)


@require_POST
def item_change_status(request, item_id):
    """HTMX endpoint to change item status."""
    item = get_object_or_404(Item, id=item_id)
    new_status = request.POST.get('status')
    
    if not new_status:
        return HttpResponse("Missing 'status' parameter", status=400)
    
    try:
        guard = ItemWorkflowGuard()
        guard.transition(item, new_status, actor=request.user if request.user.is_authenticated else None)
        
        # Return updated status badge
        response = render(request, 'partials/item_status_badge.html', {'item': item})
        response['HX-Trigger'] = 'statusChanged'
        return response
        
    except ValidationError as e:
        return HttpResponse(str(e), status=400)


@require_POST
def item_add_comment(request, item_id):
    """HTMX endpoint to add a comment to an item."""
    item = get_object_or_404(Item, id=item_id)
    body = request.POST.get('body', '').strip()
    
    if not body:
        return HttpResponse("Comment body cannot be empty", status=400)
    
    # Create comment
    comment = ItemComment.objects.create(
        item=item,
        author=request.user if request.user.is_authenticated else None,
        body=body,
    )
    
    # Log activity
    activity_service = ActivityService()
    activity_service.log(
        verb='comment.added',
        target=item,
        actor=request.user if request.user.is_authenticated else None,
        summary=f"Added comment",
    )
    
    # Return updated comments list
    response = redirect('item-comments-tab', item_id=item.id)
    response['HX-Trigger'] = 'commentAdded'
    return response


@require_POST
def item_upload_attachment(request, item_id):
    """HTMX endpoint to upload an attachment to an item."""
    item = get_object_or_404(Item, id=item_id)
    
    if 'file' not in request.FILES:
        return HttpResponse("No file provided", status=400)
    
    uploaded_file = request.FILES['file']
    
    try:
        # Store attachment
        storage_service = AttachmentStorageService()
        attachment = storage_service.store_attachment(
            file=uploaded_file,
            target=item,
            role=AttachmentRole.ITEM_FILE,
            created_by=request.user if request.user.is_authenticated else None,
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='attachment.uploaded',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Uploaded file: {attachment.original_name}",
        )
        
        # Return updated attachments list
        response = redirect('item-attachments-tab', item_id=item.id)
        response['HX-Trigger'] = 'attachmentUploaded'
        return response
        
    except Exception as e:
        return HttpResponse(f"Upload failed: {str(e)}", status=400)


@require_POST
def item_classify(request, item_id):
    """
    HTMX endpoint to classify an inbox item.
    
    Expects POST parameter 'action' with value 'backlog' or 'start'.
    Returns updated table row HTML.
    """
    item = get_object_or_404(Item, id=item_id)
    action = request.POST.get('action')
    
    if not action:
        return HttpResponse(
            "Missing 'action' parameter. Valid actions: 'backlog', 'start'", 
            status=400
        )
    
    try:
        # Use workflow guard to transition
        guard = ItemWorkflowGuard()
        guard.classify_inbox(item, action, actor=request.user if request.user.is_authenticated else None)
        
        # Return empty response with HX-Trigger to remove row
        # The row will be hidden by HTMX swap
        response = HttpResponse("")
        response['HX-Trigger'] = 'itemClassified'
        return response
        
    except ValidationError as e:
        return HttpResponse(str(e), status=400)

