from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q, Count
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
import openai
from google import genai
from django.utils.safestring import mark_safe
import markdown
import bleach
from .models import (
    Project, Item, ItemStatus, ItemComment, User, Release, Node, ItemType, Organisation,
    Attachment, AttachmentLink, AttachmentRole, Activity, ProjectStatus, NodeType, ReleaseStatus,
    AIProvider, AIModel, AIProviderType, AIJobsHistory, UserOrganisation, UserRole)

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



# ============================================================================
# Organisation CRUD Views
# ============================================================================

def organisations(request):
    """Organisations list view with filtering."""
    orgs = Organisation.objects.all()
    
    # Annotate with user and project counts
    orgs = orgs.annotate(
        user_count=Count('user_organisations', distinct=True),
        project_count=Count('projects', distinct=True)
    )
    
    # Server-side search filter
    q = request.GET.get('q', '')
    if q:
        orgs = orgs.filter(name__icontains=q)
    
    context = {
        'organisations': orgs,
        'search_query': q,
    }
    return render(request, 'organisations.html', context)


def organisation_create(request):
    """Organisation create page view."""
    if request.method == 'GET':
        # Show the create form
        context = {
            'organisation': None,
        }
        return render(request, 'organisation_form.html', context)
    
    # Handle POST request (HTMX form submission)
    try:
        organisation = Organisation.objects.create(
            name=request.POST.get('name')
        )
        return JsonResponse({
            'success': True,
            'message': 'Organisation created successfully',
            'organisation_id': organisation.id,
            'redirect': f'/organisations/{organisation.id}/'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def organisation_edit(request, id):
    """Organisation edit page view."""
    organisation = get_object_or_404(Organisation, id=id)
    
    if request.method == 'GET':
        # Show the edit form
        context = {
            'organisation': organisation,
        }
        return render(request, 'organisation_form.html', context)


def organisation_update(request, id):
    """Organisation update endpoint."""
    organisation = get_object_or_404(Organisation, id=id)
    
    # Handle POST request (HTMX form submission)
    try:
        organisation.name = request.POST.get('name', organisation.name)
        organisation.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Organisation updated successfully',
            'redirect': f'/organisations/{organisation.id}/'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def organisation_detail(request, id):
    """Organisation detail page view."""
    organisation = get_object_or_404(
        Organisation.objects.annotate(
            user_count=Count('user_organisations', distinct=True),
            project_count=Count('projects', distinct=True)
        ),
        id=id
    )
    
    # Get all users for the user management
    all_users = User.objects.filter(active=True).order_by('name')
    
    # Get all projects for the project linking
    all_projects = Project.objects.all().order_by('name')
    
    # Get users in this organisation
    user_organisations = organisation.user_organisations.select_related('user').order_by('user__name')
    
    # Get projects linked to this organisation
    projects = organisation.projects.all().order_by('name')
    
    context = {
        'organisation': organisation,
        'all_users': all_users,
        'all_projects': all_projects,
        'user_organisations': user_organisations,
        'projects': projects,
        'user_roles': UserRole.choices,
        'default_role': UserRole.USER,
    }
    return render(request, 'organisation_detail.html', context)


def organisation_delete(request, id):
    """Delete an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    
    try:
        organisation.delete()
        return JsonResponse({'success': True, 'redirect': '/organisations/'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def organisation_add_user(request, id):
    """Add a user to an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    user_id = request.POST.get('user_id')
    is_primary = request.POST.get('is_primary', 'false') == 'true'
    role = request.POST.get('role', UserRole.USER)
    
    if not user_id:
        return JsonResponse({'success': False, 'error': 'User ID required'}, status=400)
    
    try:
        user = get_object_or_404(User, id=user_id)
        
        # Check if user is already in this organisation
        if organisation.user_organisations.filter(user=user).exists():
            return JsonResponse({'success': False, 'error': 'User already in this organisation'}, status=400)
        
        # Create the UserOrganisation relationship
        UserOrganisation.objects.create(
            organisation=organisation,
            user=user,
            role=role,
            is_primary=is_primary
        )
        
        return JsonResponse({'success': True, 'message': 'User added successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def organisation_remove_user(request, id):
    """Remove a user from an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    user_id = request.POST.get('user_id')
    
    if not user_id:
        return JsonResponse({'success': False, 'error': 'User ID required'}, status=400)
    
    try:
        user = get_object_or_404(User, id=user_id)
        organisation.user_organisations.filter(user=user).delete()
        return JsonResponse({'success': True, 'message': 'User removed successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def organisation_update_user(request, id):
    """Update a user's role and primary status in an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    user_id = request.POST.get('user_id')
    role = request.POST.get('role')
    is_primary = request.POST.get('is_primary', 'false') == 'true'
    
    if not user_id:
        return JsonResponse({'success': False, 'error': 'User ID required'}, status=400)
    
    if not role:
        return JsonResponse({'success': False, 'error': 'Role required'}, status=400)
    
    try:
        user = get_object_or_404(User, id=user_id)
        user_org = get_object_or_404(UserOrganisation, organisation=organisation, user=user)
        
        # Update the role and primary status
        user_org.role = role
        user_org.is_primary = is_primary
        user_org.save()
        
        return JsonResponse({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def organisation_link_project(request, id):
    """Link a project to an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    project_id = request.POST.get('project_id')
    
    if not project_id:
        return JsonResponse({'success': False, 'error': 'Project ID required'}, status=400)
    
    try:
        project = get_object_or_404(Project, id=project_id)
        project.clients.add(organisation)
        return JsonResponse({'success': True, 'message': 'Project linked successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def organisation_unlink_project(request, id):
    """Unlink a project from an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    project_id = request.POST.get('project_id')
    
    if not project_id:
        return JsonResponse({'success': False, 'error': 'Project ID required'}, status=400)
    
    try:
        project = get_object_or_404(Project, id=project_id)
        project.clients.remove(organisation)
        return JsonResponse({'success': True, 'message': 'Project unlinked successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ============================================================================
# AI Provider CRUD Views
# ============================================================================

def ai_providers(request):
    """AI Providers list view with filtering."""
    providers = AIProvider.objects.all()
    
    # Annotate with model count
    providers = providers.annotate(
        model_count=Count('models')
    )
    
    # Search filter
    q = request.GET.get('q', '')
    if q:
        providers = providers.filter(
            Q(name__icontains=q) | Q(provider_type__icontains=q)
        )
    
    # Provider type filter
    provider_type_filter = request.GET.get('provider_type', '')
    if provider_type_filter:
        providers = providers.filter(provider_type=provider_type_filter)
    
    # Active filter
    active_filter = request.GET.get('active', '')
    if active_filter:
        providers = providers.filter(active=(active_filter == 'true'))
    
    # Get provider types for filter dropdown
    provider_types = AIProviderType.choices
    
    context = {
        'providers': providers,
        'search_query': q,
        'provider_types': provider_types,
        'selected_provider_type': provider_type_filter,
        'selected_active': active_filter,
    }
    return render(request, 'ai_providers.html', context)


def ai_provider_detail(request, id):
    """AI Provider detail view with models."""
    provider = get_object_or_404(AIProvider, id=id)
    
    # Get all models for this provider
    models = provider.models.all().order_by('-is_default', 'name')
    
    # Get provider types for dropdown
    provider_types = AIProviderType.choices
    
    context = {
        'provider': provider,
        'models': models,
        'provider_types': provider_types,
    }
    return render(request, 'ai_provider_detail.html', context)


def ai_provider_create(request):
    """Create a new AI Provider."""
    if request.method == 'GET':
        provider_types = AIProviderType.choices
        context = {
            'provider': None,
            'provider_types': provider_types,
        }
        return render(request, 'ai_provider_form.html', context)
    
    # Handle POST request
    try:
        provider = AIProvider.objects.create(
            name=request.POST.get('name'),
            provider_type=request.POST.get('provider_type'),
            api_key=request.POST.get('api_key'),
            organization_id=request.POST.get('organization_id', ''),
            active=request.POST.get('active') == 'on'
        )
        
        # Return HTMX response with redirect
        response = HttpResponse()
        response['HX-Redirect'] = f'/ai-providers/{provider.id}/'
        return response
        
    except Exception as e:
        return HttpResponse(f"Error creating provider: {str(e)}", status=400)


@require_http_methods(["POST"])
def ai_provider_update(request, id):
    """Update AI Provider."""
    provider = get_object_or_404(AIProvider, id=id)
    
    try:
        provider.name = request.POST.get('name', provider.name)
        provider.provider_type = request.POST.get('provider_type', provider.provider_type)
        provider.organization_id = request.POST.get('organization_id', provider.organization_id)
        provider.active = request.POST.get('active') == 'on'
        
        # Only update api_key if a new one is provided
        api_key = request.POST.get('api_key', '').strip()
        if api_key:
            provider.api_key = api_key
        
        provider.save()
        
        # Return success toast trigger
        response = HttpResponse()
        response['HX-Trigger'] = 'showToast'
        return response
        
    except Exception as e:
        return HttpResponse(f"Error updating provider: {str(e)}", status=400)


@require_http_methods(["POST"])
def ai_provider_delete(request, id):
    """Delete AI Provider."""
    provider = get_object_or_404(AIProvider, id=id)
    
    try:
        provider.delete()
        
        # Return redirect to list
        response = HttpResponse()
        response['HX-Redirect'] = '/ai-providers/'
        return response
        
    except Exception as e:
        return HttpResponse(f"Error deleting provider: {str(e)}", status=400)


@require_http_methods(["GET"])
def ai_provider_get_api_key(request, id):
    """Get decrypted API key for copying. Requires authentication."""
    # Check if user is authenticated
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    provider = get_object_or_404(AIProvider, id=id)
    
    # Return the actual API key for clipboard copy
    return JsonResponse({
        'api_key': provider.api_key
    })


@require_http_methods(["POST"])
def ai_provider_fetch_models(request, id):
    """Fetch available models from the provider API and save them to the database."""
    provider = get_object_or_404(AIProvider, id=id)
    
    try:
        models_data = []
        
        if provider.provider_type == 'OpenAI':
            # Use OpenAI API to list models
            openai_client = openai.OpenAI(api_key=provider.api_key)
            models_list = openai_client.models.list()
            
            # Include all GPT models without restrictive filtering
            # This includes gpt-3.5, gpt-4, gpt-4o, gpt-5, o1, o3, and all variants
            for model in models_list.data:
                model_id_lower = model.id.lower()
                # Include all GPT models (gpt-*, o1-*, o3-*) but exclude embeddings and other non-chat models
                if (model_id_lower.startswith('gpt-') or 
                    model_id_lower.startswith('o1-') or 
                    model_id_lower.startswith('o3-')):
                    models_data.append({
                        'name': model.id,
                        'model_id': model.id
                    })
        
        elif provider.provider_type == 'Gemini':
            # Use Gemini API to list all available models
            gemini_client = genai.Client(api_key=provider.api_key)
            models_list = gemini_client.models.list()
            
            # Filter to only generative models (exclude embedding models)
            for model in models_list:
                # Only include models that support generateContent
                if (hasattr(model, 'supported_generation_methods') and 
                    model.supported_generation_methods and 
                    'generateContent' in model.supported_generation_methods):
                    # Use the model name without 'models/' prefix if present
                    model_id = getattr(model, 'name', str(model)).replace('models/', '')
                    # Use display_name if available, otherwise use the model_id
                    model_name = getattr(model, 'display_name', None) or model_id
                    models_data.append({
                        'name': model_name,
                        'model_id': model_id
                    })
        
        elif provider.provider_type == 'Claude':
            # For Claude, use predefined list (updated as of Jan 2026)
            models_data = [
                {'name': 'Claude 3.5 Sonnet', 'model_id': 'claude-3-5-sonnet-20241022'},
                {'name': 'Claude 3 Opus', 'model_id': 'claude-3-opus-20240229'},
                {'name': 'Claude 3 Sonnet', 'model_id': 'claude-3-sonnet-20240229'},
                {'name': 'Claude 3 Haiku', 'model_id': 'claude-3-haiku-20240307'},
            ]
        
        # Save fetched models to the database
        created_count = 0
        existing_count = 0
        
        for model_data in models_data:
            model, created = AIModel.objects.get_or_create(
                provider=provider,
                model_id=model_data['model_id'],
                defaults={
                    'name': model_data['name'],
                    'active': True,
                    'is_default': False,
                    'input_price_per_1m_tokens': None,
                    'output_price_per_1m_tokens': None,
                }
            )
            if created:
                created_count += 1
            else:
                existing_count += 1
        
        return JsonResponse({
            'success': True,
            'models': models_data,
            'created_count': created_count,
            'existing_count': existing_count,
            'total_count': len(models_data)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Failed to fetch models: {str(e)}'
        }, status=400)


@require_http_methods(["POST"])
def ai_model_create(request, provider_id):
    """Create a new AI Model for a provider."""
    provider = get_object_or_404(AIProvider, id=provider_id)
    
    try:
        # Get input values and convert empty strings to None for decimal fields
        input_price = request.POST.get('input_price_per_1m_tokens', '').strip()
        output_price = request.POST.get('output_price_per_1m_tokens', '').strip()
        
        model = AIModel.objects.create(
            provider=provider,
            name=request.POST.get('name'),
            model_id=request.POST.get('model_id'),
            input_price_per_1m_tokens=input_price if input_price else None,
            output_price_per_1m_tokens=output_price if output_price else None,
            active=request.POST.get('active') == 'on',
            is_default=request.POST.get('is_default') == 'on'
        )
        
        # If this is set as default, unset other defaults
        if model.is_default:
            AIModel.objects.filter(provider=provider).exclude(id=model.id).update(is_default=False)
        
        # Return updated models list
        models = provider.models.all().order_by('-is_default', 'name')
        context = {
            'provider': provider,
            'models': models,
        }
        return render(request, 'partials/ai_models_list.html', context)
        
    except Exception as e:
        return HttpResponse(f"Error creating model: {str(e)}", status=400)


@require_http_methods(["POST"])
def ai_model_update(request, provider_id, model_id):
    """Update an AI Model."""
    provider = get_object_or_404(AIProvider, id=provider_id)
    model = get_object_or_404(AIModel, id=model_id, provider=provider)
    
    try:
        model.name = request.POST.get('name', model.name)
        model.model_id = request.POST.get('model_id', model.model_id)
        
        # Handle decimal fields - convert empty strings to None
        input_price = request.POST.get('input_price_per_1m_tokens', '').strip()
        output_price = request.POST.get('output_price_per_1m_tokens', '').strip()
        model.input_price_per_1m_tokens = input_price if input_price else None
        model.output_price_per_1m_tokens = output_price if output_price else None
        
        model.active = request.POST.get('active') == 'on'
        model.is_default = request.POST.get('is_default') == 'on'
        model.save()
        
        # If this is set as default, unset other defaults
        if model.is_default:
            AIModel.objects.filter(provider=provider).exclude(id=model.id).update(is_default=False)
        
        # Return updated models list
        models = provider.models.all().order_by('-is_default', 'name')
        context = {
            'provider': provider,
            'models': models,
        }
        return render(request, 'partials/ai_models_list.html', context)
        
    except Exception as e:
        return HttpResponse(f"Error updating model: {str(e)}", status=400)


@require_http_methods(["POST"])
def ai_model_delete(request, provider_id, model_id):
    """Delete an AI Model."""
    provider = get_object_or_404(AIProvider, id=provider_id)
    model = get_object_or_404(AIModel, id=model_id, provider=provider)
    
    try:
        model.delete()
        
        # Return updated models list
        models = provider.models.all().order_by('-is_default', 'name')
        context = {
            'provider': provider,
            'models': models,
        }
        return render(request, 'partials/ai_models_list.html', context)
        
    except Exception as e:
        return HttpResponse(f"Error deleting model: {str(e)}", status=400)


def ai_jobs_history(request):
    """AI Jobs History list view with filtering and pagination."""
    jobs = AIJobsHistory.objects.select_related('user', 'provider', 'model').all()
    
    # Order by timestamp descending (newest first)
    jobs = jobs.order_by('-timestamp')
    
    # Search filter (searches in agent name and error message)
    q = request.GET.get('q', '')
    if q:
        jobs = jobs.filter(
            Q(agent__icontains=q) | Q(error_message__icontains=q)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    # Provider filter
    provider_filter = request.GET.get('provider', '')
    if provider_filter:
        try:
            jobs = jobs.filter(provider_id=int(provider_filter))
        except (ValueError, TypeError):
            provider_filter = ''
    
    # Model filter
    model_filter = request.GET.get('model', '')
    if model_filter:
        try:
            jobs = jobs.filter(model_id=int(model_filter))
        except (ValueError, TypeError):
            model_filter = ''
    
    # Pagination - 25 items per page
    paginator = Paginator(jobs, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Get all providers and models for filter dropdowns
    providers = AIProvider.objects.all().order_by('name')
    models = AIModel.objects.all().order_by('name')
    
    # Get status choices from model
    from .models import AIJobStatus
    status_choices = AIJobStatus.choices
    
    context = {
        'page_obj': page_obj,
        'search_query': q,
        'providers': providers,
        'models': models,
        'status_choices': status_choices,
        'selected_status': status_filter,
        'selected_provider': provider_filter,
        'selected_model': model_filter,
    }
    return render(request, 'ai_jobs_history.html', context)
