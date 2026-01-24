from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Count
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.safestring import mark_safe
import markdown
import bleach
from .models import (
    Project, Item, ItemStatus, ItemComment, User, Release, Node, ItemType, Organisation,
    Attachment, AttachmentLink, AttachmentRole, Activity, ProjectStatus, NodeType, ReleaseStatus)
from .services.workflow import ItemWorkflowGuard
from .services.activity import ActivityService
from .services.storage import AttachmentStorageService

# Create markdown parser once at module level for better performance
MARKDOWN_PARSER = markdown.Markdown(extensions=['extra', 'fenced_code'])

# Allowed HTML tags and attributes for sanitization
ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'strong', 'em', 'u', 'strike',
    'ul', 'ol', 'li',
    'blockquote', 'code', 'pre',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'div', 'span'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'code': ['class'],
    'pre': ['class'],
    'div': ['class'],
    'span': ['class'],
}

def home(request):
    """Home page view."""
    return render(request, 'home.html')

def dashboard(request):
    """Dashboard page view."""
    return render(request, 'dashboard.html')

def projects(request):
    """Projects page view."""
    projects_list = Project.objects.all()
    
    # Annotate with item counts by status
    projects_list = projects_list.annotate(
        inbox_count=Count('items', filter=Q(items__status=ItemStatus.INBOX)),
        backlog_count=Count('items', filter=Q(items__status=ItemStatus.BACKLOG)),
        working_count=Count('items', filter=Q(items__status=ItemStatus.WORKING)),
        testing_count=Count('items', filter=Q(items__status=ItemStatus.TESTING)),
        ready_for_release_count=Count('items', filter=Q(items__status=ItemStatus.READY_FOR_RELEASE))
    )
    
    # Server-side search filter
    q = request.GET.get('q', '')
    if q:
        projects_list = projects_list.filter(name__icontains=q)
    
    # Filter by organisation
    org_filter = request.GET.get('organisation', '')
    if org_filter:
        projects_list = projects_list.filter(clients__id=org_filter)
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        projects_list = projects_list.filter(status=status_filter)
    
    # Get all organisations and statuses for filter dropdowns
    organisations = Organisation.objects.all().order_by('name')
    statuses = ProjectStatus.choices
    
    context = {
        'projects': projects_list,
        'search_query': q,
        'organisations': organisations,
        'statuses': statuses,
        'selected_organisation': org_filter,
        'selected_status': status_filter,
    }
    return render(request, 'projects.html', context)

def project_create(request):
    """Project create page view."""
    if request.method == 'GET':
        # Show the create form
        statuses = ProjectStatus.choices
        context = {
            'project': None,
            'statuses': statuses,
        }
        return render(request, 'project_form.html', context)
    
    # Handle POST request (HTMX form submission)
    try:
        project = Project.objects.create(
            name=request.POST.get('name'),
            description=request.POST.get('description', ''),
            status=request.POST.get('status', ProjectStatus.NEW),
            github_owner=request.POST.get('github_owner', ''),
            github_repo=request.POST.get('github_repo', '')
        )
        return JsonResponse({
            'success': True,
            'message': 'Project created successfully',
            'project_id': project.id,
            'redirect': f'/projects/{project.id}/'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

def project_edit(request, id):
    """Project edit page view."""
    project = get_object_or_404(Project, id=id)
    
    if request.method == 'GET':
        # Show the edit form
        statuses = ProjectStatus.choices
        context = {
            'project': project,
            'statuses': statuses,
        }
        return render(request, 'project_form.html', context)
    
    # Handle POST request (HTMX form submission)
    try:
        project.name = request.POST.get('name', project.name)
        project.description = request.POST.get('description', project.description)
        project.status = request.POST.get('status', project.status)
        project.github_owner = request.POST.get('github_owner', project.github_owner)
        project.github_repo = request.POST.get('github_repo', project.github_repo)
        project.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Project updated successfully',
            'redirect': f'/projects/{project.id}/'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

def project_detail(request, id):
    """Project detail page view."""
    project = get_object_or_404(
        Project.objects.annotate(
            inbox_count=Count('items', filter=Q(items__status=ItemStatus.INBOX)),
            backlog_count=Count('items', filter=Q(items__status=ItemStatus.BACKLOG)),
            working_count=Count('items', filter=Q(items__status=ItemStatus.WORKING)),
        ),
        id=id
    )
    
    # Render markdown description to HTML with sanitization
    description_html = None
    if project.description:
        # Reset parser state for clean conversion
        MARKDOWN_PARSER.reset()
        # Convert markdown to HTML
        html = MARKDOWN_PARSER.convert(project.description)
        # Sanitize HTML to prevent XSS attacks
        sanitized_html = bleach.clean(
            html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            strip=True
        )
        description_html = mark_safe(sanitized_html)
    
    # Get all organisations for the client management
    all_organisations = Organisation.objects.all().order_by('name')
    
    # Get all item types for adding new items
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    
    # Get node types for adding new nodes
    node_types = NodeType.choices
    
    context = {
        'project': project,
        'description_html': description_html,
        'all_organisations': all_organisations,
        'item_types': item_types,
        'node_types': node_types,
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
    comments = item.comments.select_related('author').order_by('created_at')
    context = {
        'item': item,
        'comments': comments,
    }
    response = render(request, 'partials/item_comments_tab.html', context)
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
        response = render(request, 'partials/item_attachments_tab.html', context)
        response['HX-Trigger'] = 'attachmentUploaded'
        return response
        
    except ValidationError as e:
        return HttpResponse(f"Validation error: {str(e)}", status=400)
    except PermissionError as e:
        return HttpResponse("Permission denied", status=403)
    except Exception as e:
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Attachment upload failed for item {item_id}: {str(e)}")
        return HttpResponse("Upload failed. Please try again.", status=500)


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


def item_create(request):
    """Item create page view."""
    if request.method == 'GET':
        # Show the create form
        projects = Project.objects.all().order_by('name')
        item_types = ItemType.objects.filter(is_active=True).order_by('name')
        organisations = Organisation.objects.all().order_by('name')
        users = User.objects.all().order_by('name')
        statuses = ItemStatus.choices
        
        context = {
            'item': None,
            'projects': projects,
            'item_types': item_types,
            'organisations': organisations,
            'users': users,
            'statuses': statuses,
        }
        return render(request, 'item_form.html', context)
    
    # Handle POST request (HTMX form submission)
    try:
        project_id = request.POST.get('project')
        project = get_object_or_404(Project, id=project_id)
        
        type_id = request.POST.get('type')
        item_type = get_object_or_404(ItemType, id=type_id)
        
        # Create the item
        item = Item(
            project=project,
            title=request.POST.get('title', ''),
            description=request.POST.get('description', ''),
            solution_description=request.POST.get('solution_description', ''),
            type=item_type,
            status=request.POST.get('status', ItemStatus.INBOX),
        )
        
        # Set optional fields
        org_id = request.POST.get('organisation')
        if org_id:
            item.organisation = get_object_or_404(Organisation, id=org_id)
        
        requester_id = request.POST.get('requester')
        if requester_id:
            item.requester = get_object_or_404(User, id=requester_id)
        
        assigned_to_id = request.POST.get('assigned_to')
        if assigned_to_id:
            item.assigned_to = get_object_or_404(User, id=assigned_to_id)
        
        parent_id = request.POST.get('parent')
        if parent_id:
            item.parent = get_object_or_404(Item, id=parent_id)
        
        solution_release_id = request.POST.get('solution_release')
        if solution_release_id:
            item.solution_release = get_object_or_404(Release, id=solution_release_id)
        
        item.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.created',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Created item: {item.title}",
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Item created successfully',
            'redirect': f'/items/{item.id}/',
            'item_id': item.id
        })
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        # Log the full error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Item creation failed: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to create item. Please check your input.'}, status=400)


def item_edit(request, item_id):
    """Item edit page view."""
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release', 'parent'
        ),
        id=item_id
    )
    
    if request.method == 'GET':
        # Show the edit form
        projects = Project.objects.all().order_by('name')
        item_types = ItemType.objects.filter(is_active=True).order_by('name')
        organisations = Organisation.objects.all().order_by('name')
        users = User.objects.all().order_by('name')
        statuses = ItemStatus.choices
        
        # Get releases for the current project
        releases = Release.objects.filter(project=item.project).order_by('-version')
        
        # Get potential parent items from the same project
        parent_items = Item.objects.filter(project=item.project).exclude(id=item.id).order_by('title')
        
        context = {
            'item': item,
            'projects': projects,
            'item_types': item_types,
            'organisations': organisations,
            'users': users,
            'statuses': statuses,
            'releases': releases,
            'parent_items': parent_items,
        }
        return render(request, 'item_form.html', context)
    
    # Handle POST request (HTMX form submission) - handled by item_update
    return redirect('item-update', item_id=item_id)


@require_http_methods(["POST"])
def item_update(request, item_id):
    """Update item details."""
    item = get_object_or_404(Item, id=item_id)
    
    try:
        # Update basic fields
        item.title = request.POST.get('title', item.title)
        item.description = request.POST.get('description', item.description)
        item.solution_description = request.POST.get('solution_description', item.solution_description)
        item.status = request.POST.get('status', item.status)
        
        # Update foreign key fields
        project_id = request.POST.get('project')
        if project_id:
            item.project = get_object_or_404(Project, id=project_id)
        
        type_id = request.POST.get('type')
        if type_id:
            item.type = get_object_or_404(ItemType, id=type_id)
        
        # Update optional foreign key fields
        org_id = request.POST.get('organisation')
        if org_id:
            item.organisation = get_object_or_404(Organisation, id=org_id)
        elif org_id == '':  # Empty string means clear the field
            item.organisation = None
        
        requester_id = request.POST.get('requester')
        if requester_id:
            item.requester = get_object_or_404(User, id=requester_id)
        elif requester_id == '':
            item.requester = None
        
        assigned_to_id = request.POST.get('assigned_to')
        if assigned_to_id:
            item.assigned_to = get_object_or_404(User, id=assigned_to_id)
        elif assigned_to_id == '':
            item.assigned_to = None
        
        parent_id = request.POST.get('parent')
        if parent_id:
            item.parent = get_object_or_404(Item, id=parent_id)
        elif parent_id == '':
            item.parent = None
        
        solution_release_id = request.POST.get('solution_release')
        if solution_release_id:
            item.solution_release = get_object_or_404(Release, id=solution_release_id)
        elif solution_release_id == '':
            item.solution_release = None
        
        item.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.updated',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Updated item: {item.title}",
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Item updated successfully',
            'redirect': f'/items/{item.id}/'
        })
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        # Log the full error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Item update failed for item {item_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to update item. Please check your input.'}, status=400)


@require_http_methods(["POST"])
def item_delete(request, item_id):
    """Delete an item."""
    item = get_object_or_404(Item, id=item_id)
    project_id = item.project.id
    
    try:
        item.delete()
        return JsonResponse({
            'success': True,
            'message': 'Item deleted successfully',
            'redirect': f'/projects/{project_id}/'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


# Project CRUD operations
@require_http_methods(["POST"])
def project_update(request, id):
    """Update project details."""
    project = get_object_or_404(Project, id=id)
    
    try:
        project.name = request.POST.get('name', project.name)
        project.description = request.POST.get('description', project.description)
        project.status = request.POST.get('status', project.status)
        project.github_owner = request.POST.get('github_owner', project.github_owner)
        project.github_repo = request.POST.get('github_repo', project.github_repo)
        project.save()
        return JsonResponse({'success': True, 'message': 'Project updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def project_delete(request, id):
    """Delete a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        project.delete()
        return JsonResponse({'success': True, 'redirect': '/projects/'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def project_add_client(request, id):
    """Add a client (organisation) to a project."""
    project = get_object_or_404(Project, id=id)
    org_id = request.POST.get('organisation_id')
    
    if not org_id:
        return JsonResponse({'success': False, 'error': 'Organisation ID required'}, status=400)
    
    try:
        organisation = get_object_or_404(Organisation, id=org_id)
        project.clients.add(organisation)
        return JsonResponse({'success': True, 'message': 'Client added successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def project_remove_client(request, id):
    """Remove a client (organisation) from a project."""
    project = get_object_or_404(Project, id=id)
    org_id = request.POST.get('organisation_id')
    
    if not org_id:
        return JsonResponse({'success': False, 'error': 'Organisation ID required'}, status=400)
    
    try:
        organisation = get_object_or_404(Organisation, id=org_id)
        project.clients.remove(organisation)
        return JsonResponse({'success': True, 'message': 'Client removed successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def project_add_item(request, id):
    """Add a new item to a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        title = request.POST.get('title')
        description = request.POST.get('description', '')
        type_id = request.POST.get('type_id')
        
        if not title or not type_id:
            return JsonResponse({'success': False, 'error': 'Title and Type are required'}, status=400)
        
        item_type = get_object_or_404(ItemType, id=type_id)
        
        item = Item.objects.create(
            project=project,
            title=title,
            description=description,
            type=item_type,
            status=ItemStatus.INBOX
        )
        
        return JsonResponse({'success': True, 'message': 'Item created successfully', 'item_id': item.id})
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def project_add_node(request, id):
    """Add a new node to a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        name = request.POST.get('name')
        node_type = request.POST.get('type')
        description = request.POST.get('description', '')
        
        if not name or not node_type:
            return JsonResponse({'success': False, 'error': 'Name and Type are required'}, status=400)
        
        node = Node.objects.create(
            project=project,
            name=name,
            type=node_type,
            description=description
        )
        
        return JsonResponse({'success': True, 'message': 'Node created successfully', 'node_id': node.id})
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def project_add_release(request, id):
    """Add a new release to a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        name = request.POST.get('name')
        version = request.POST.get('version')
        
        if not name or not version:
            return JsonResponse({'success': False, 'error': 'Name and Version are required'}, status=400)
        
        release = Release.objects.create(
            project=project,
            name=name,
            version=version,
            status=ReleaseStatus.PLANNED
        )
        
        return JsonResponse({'success': True, 'message': 'Release created successfully', 'release_id': release.id})
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


