from django.shortcuts import render

def home(request):
    """Home page view."""
    return render(request, 'home.html')

def dashboard(request):
    """Dashboard page view."""
    return render(request, 'dashboard.html')

def projects(request):
    """Projects page view."""
    return render(request, 'projects.html')

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

