from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.db import models
from .models import Project, Item, ItemStatus
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

