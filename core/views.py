from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
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
    return render(request, 'items_backlog.html')

def items_working(request):
    """Items Working page view."""
    return render(request, 'items_working.html')

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
        return HttpResponse("Missing action parameter", status=400)
    
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

