from django.shortcuts import render, get_object_or_404
from .models import Project

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
    return render(request, 'items_inbox.html')

def items_backlog(request):
    """Items Backlog page view."""
    return render(request, 'items_backlog.html')

def items_working(request):
    """Items Working page view."""
    return render(request, 'items_working.html')

def changes(request):
    """Changes page view."""
    return render(request, 'changes.html')

