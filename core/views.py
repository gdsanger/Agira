from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from .models import (
    Project, Item, ItemStatus, Organisation, ItemType, Node, Release,
    ProjectStatus, NodeType, ReleaseStatus
)
from .services.workflow import ItemWorkflowGuard

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

def project_detail(request, id):
    """Project detail page view."""
    project = get_object_or_404(Project, id=id)
    
    # Get all organisations for the client management
    all_organisations = Organisation.objects.all().order_by('name')
    
    # Get all item types for adding new items
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    
    # Get node types for adding new nodes
    node_types = NodeType.choices
    
    context = {
        'project': project,
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


