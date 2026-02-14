"""
Views for First AID (First AI Documentation) app.
"""
import json
import logging
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt

from core.models import Project
from .services.firstaid_service import FirstAIDService

logger = logging.getLogger(__name__)


@login_required
def firstaid_home(request):
    """
    Main First AID interface.
    
    Displays 3-column layout:
    - Left: Sources (Items, GitHub Issues/PRs, Attachments)
    - Middle: Chat interface
    - Right: Tools/Actions
    """
    # Get all projects for the project selector
    projects = Project.objects.all().order_by('name')
    
    # Get selected project from query param or session
    project_id = request.GET.get('project')
    if not project_id:
        project_id = request.session.get('firstaid_project_id')
    
    project = None
    sources = None
    
    if project_id:
        try:
            project = get_object_or_404(Project, id=project_id)
            request.session['firstaid_project_id'] = project_id
            
            # Load sources for the project
            service = FirstAIDService()
            sources = service.get_project_sources(project_id=project.id, user=request.user)
        except Project.DoesNotExist:
            pass
    
    context = {
        'projects': projects,
        'selected_project': project,
        'sources': sources,
    }
    
    return render(request, 'firstaid/home.html', context)


@login_required
@require_POST
def firstaid_chat(request):
    """
    Process a chat message and return the response.
    
    Expects JSON payload:
    {
        "question": "User's question",
        "project_id": 123
    }
    
    Returns JSON:
    {
        "answer": "AI response",
        "sources": [...],
        "summary": "...",
        "stats": {...}
    }
    """
    try:
        data = json.loads(request.body)
        question = data.get('question', '').strip()
        project_id = data.get('project_id')
        
        if not question:
            return JsonResponse({'error': 'Question is required'}, status=400)
        
        if not project_id:
            return JsonResponse({'error': 'Project ID is required'}, status=400)
        
        # Process the question
        service = FirstAIDService()
        result = service.chat(
            project_id=int(project_id),
            question=question,
            user=request.user,
        )
        
        return JsonResponse(result)
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in firstaid_chat: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def firstaid_sources(request):
    """
    Return sources for a project (HTMX endpoint).
    
    Query params:
    - project_id: Project ID
    
    Returns HTML partial with sources list.
    """
    project_id = request.GET.get('project_id')
    
    if not project_id:
        return HttpResponse('<p class="text-muted">Select a project to view sources.</p>')
    
    try:
        project = get_object_or_404(Project, id=project_id)
        service = FirstAIDService()
        sources = service.get_project_sources(project_id=project.id, user=request.user)
        
        context = {
            'sources': sources,
            'project': project,
        }
        
        return render(request, 'firstaid/partials/sources.html', context)
    
    except Exception as e:
        logger.error(f"Error loading sources: {e}", exc_info=True)
        return HttpResponse(f'<p class="text-danger">Error loading sources: {str(e)}</p>')


@login_required
@require_POST
def generate_kb_article(request):
    """
    Generate a Knowledge Base article from context.
    
    Expects JSON payload:
    {
        "context": "Chat context or selected sources",
        "project_id": 123
    }
    
    Returns JSON:
    {
        "content": "Markdown content",
        "title": "Generated title"
    }
    """
    try:
        data = json.loads(request.body)
        context = data.get('context', '').strip()
        project_id = data.get('project_id')
        
        if not context:
            return JsonResponse({'error': 'Context is required'}, status=400)
        
        if not project_id:
            return JsonResponse({'error': 'Project ID is required'}, status=400)
        
        service = FirstAIDService()
        content = service.generate_kb_article(
            project_id=int(project_id),
            context=context,
            user=request.user,
        )
        
        return JsonResponse({
            'content': content,
            'title': 'Generated Knowledge Base Article',
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error generating KB article: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def generate_documentation(request):
    """
    Generate documentation from context.
    
    Expects JSON payload:
    {
        "context": "Chat context or selected sources",
        "project_id": 123
    }
    
    Returns JSON:
    {
        "content": "Markdown content",
        "title": "Generated title"
    }
    """
    try:
        data = json.loads(request.body)
        context = data.get('context', '').strip()
        project_id = data.get('project_id')
        
        if not context:
            return JsonResponse({'error': 'Context is required'}, status=400)
        
        if not project_id:
            return JsonResponse({'error': 'Project ID is required'}, status=400)
        
        service = FirstAIDService()
        content = service.generate_documentation(
            project_id=int(project_id),
            context=context,
            user=request.user,
        )
        
        return JsonResponse({
            'content': content,
            'title': 'Generated Documentation',
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error generating documentation: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def generate_flashcards(request):
    """
    Generate flashcards from context.
    
    Expects JSON payload:
    {
        "context": "Chat context or selected sources",
        "project_id": 123
    }
    
    Returns JSON:
    {
        "flashcards": [
            {"question": "...", "answer": "..."},
            ...
        ]
    }
    """
    try:
        data = json.loads(request.body)
        context = data.get('context', '').strip()
        project_id = data.get('project_id')
        
        if not context:
            return JsonResponse({'error': 'Context is required'}, status=400)
        
        if not project_id:
            return JsonResponse({'error': 'Project ID is required'}, status=400)
        
        service = FirstAIDService()
        flashcards = service.generate_flashcards(
            project_id=int(project_id),
            context=context,
            user=request.user,
        )
        
        return JsonResponse({'flashcards': flashcards})
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error generating flashcards: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def create_issue(request):
    """
    Create an issue from chat context.
    
    Expects JSON payload:
    {
        "title": "Issue title",
        "description": "Issue description",
        "project_id": 123
    }
    
    Returns JSON:
    {
        "success": true,
        "item_id": 456,
        "url": "/items/456/"
    }
    """
    try:
        data = json.loads(request.body)
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        project_id = data.get('project_id')
        
        if not title:
            return JsonResponse({'error': 'Title is required'}, status=400)
        
        if not project_id:
            return JsonResponse({'error': 'Project ID is required'}, status=400)
        
        # Create the item
        from core.models import Item, ItemType
        
        project = get_object_or_404(Project, id=project_id)
        
        # Get or create a default item type
        item_type, _ = ItemType.objects.get_or_create(
            key='feature',
            defaults={'name': 'Feature', 'description': 'Feature request'}
        )
        
        # Create the item
        item = Item.objects.create(
            project=project,
            type=item_type,
            title=title,
            description=description,
            status='Inbox',
        )
        
        return JsonResponse({
            'success': True,
            'item_id': item.id,
            'url': f'/items/{item.id}/',
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error creating issue: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
