"""
CustomGPT Actions API Views.

This module provides HTTP API endpoints for CustomGPT Actions to interact with
Projects and Items. All endpoints require authentication via x-api-secret header.
"""
import logging
import json
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError

from core.models import Project, Item, ItemType, ItemStatus
from core.services.rag import build_context

logger = logging.getLogger(__name__)


# Helper function to serialize Project model
def serialize_project(project):
    """
    Serialize a Project instance to a dictionary.
    
    Args:
        project: Project instance
        
    Returns:
        Dictionary with project data
    """
    return {
        'id': project.id,
        'name': project.name,
        'description': project.description,
        'status': project.status,
        'github_owner': project.github_owner,
        'github_repo': project.github_repo,
    }


# Helper function to serialize Item model
def serialize_item(item):
    """
    Serialize an Item instance to a dictionary.
    
    Args:
        item: Item instance
        
    Returns:
        Dictionary with item data
    """
    return {
        'id': item.id,
        'title': item.title,
        'description': item.description,
        'user_input': item.user_input,
        'solution_description': item.solution_description,
        'status': item.status,
        'project_id': item.project_id,
        'type_id': item.type_id,
        'organisation_id': item.organisation_id,
        'requester_id': item.requester_id,
        'assigned_to_id': item.assigned_to_id,
        'parent_id': item.parent_id,
        'solution_release_id': item.solution_release_id,
        'intern': item.intern,
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'updated_at': item.updated_at.isoformat() if item.updated_at else None,
    }


# Helper function to serialize RAGContext to dict
def serialize_rag_context(context):
    """
    Serialize a RAGContext instance to a dictionary.
    
    Args:
        context: RAGContext instance
        
    Returns:
        Dictionary with RAG context data
    """
    return {
        'query': context.query,
        'alpha': context.alpha,
        'summary': context.summary,
        'items': [
            {
                'object_type': obj.object_type,
                'object_id': obj.object_id,
                'title': obj.title,
                'content': obj.content,
                'source': obj.source,
                'relevance_score': obj.relevance_score,
                'link': obj.link,
                'updated_at': obj.updated_at,
            }
            for obj in context.items
        ],
        'stats': context.stats,
        'debug': context.debug,
    }


# Projects Endpoints

@csrf_exempt
@require_http_methods(["GET"])
def api_projects_list(request):
    """
    GET /api/customgpt/projects
    
    List all projects.
    
    Returns:
        200: Array of Project objects
    """
    try:
        projects = Project.objects.all()
        return JsonResponse([serialize_project(p) for p in projects], safe=False)
    except Exception as e:
        logger.error(f"Error listing projects: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_project_detail(request, project_id):
    """
    GET /api/customgpt/projects/{project_id}
    
    Get a specific project by ID.
    
    Args:
        project_id: Project ID
        
    Returns:
        200: Project object
        404: Project not found
    """
    try:
        project = Project.objects.get(id=project_id)
        return JsonResponse(serialize_project(project))
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting project {project_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
def api_project_update_put(request, project_id):
    """
    PUT /api/customgpt/projects/{project_id}
    
    Update a project (full replacement).
    
    Args:
        project_id: Project ID
        
    Request Body:
        JSON object with project fields
        
    Returns:
        200: Updated Project object
        400: Invalid payload
        404: Project not found
    """
    try:
        project = Project.objects.get(id=project_id)
        
        # Parse request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
        
        # Update fields
        if 'name' in data:
            project.name = data['name']
        if 'description' in data:
            project.description = data['description']
        if 'status' in data:
            project.status = data['status']
        if 'github_owner' in data:
            project.github_owner = data['github_owner']
        if 'github_repo' in data:
            project.github_repo = data['github_repo']
        
        # Validate and save
        try:
            project.full_clean()
            project.save()
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)
        
        return JsonResponse(serialize_project(project))
        
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)
    except Exception as e:
        logger.error(f"Error updating project {project_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PATCH"])
def api_project_update_patch(request, project_id):
    """
    PATCH /api/customgpt/projects/{project_id}
    
    Update a project (partial update).
    
    Args:
        project_id: Project ID
        
    Request Body:
        JSON object with project fields to update
        
    Returns:
        200: Updated Project object
        400: Invalid payload
        404: Project not found
    """
    # For now, PATCH and PUT behave the same way (partial update)
    return api_project_update_put(request, project_id)


@csrf_exempt
@require_http_methods(["GET"])
def api_project_open_items(request, project_id):
    """
    GET /api/customgpt/projects/{project_id}/open-items
    
    List all items in a project with status != Closed.
    
    Args:
        project_id: Project ID
        
    Returns:
        200: Array of Item objects
        404: Project not found
    """
    try:
        # Verify project exists
        project = Project.objects.get(id=project_id)
        
        # Get all items excluding Closed status
        items = Item.objects.filter(
            project=project
        ).exclude(
            status=ItemStatus.CLOSED
        )
        
        return JsonResponse([serialize_item(item) for item in items], safe=False)
        
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting open items for project {project_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


# Items Endpoints

@csrf_exempt
@require_http_methods(["GET"])
def api_items_list(request):
    """
    GET /api/customgpt/items
    
    List all items (across all projects) with status != Closed.
    
    Returns:
        200: Array of Item objects
    """
    try:
        # Get all items excluding Closed status
        items = Item.objects.exclude(status=ItemStatus.CLOSED)
        return JsonResponse([serialize_item(item) for item in items], safe=False)
    except Exception as e:
        logger.error(f"Error listing items: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_item_detail(request, item_id):
    """
    GET /api/customgpt/items/{item_id}
    
    Get a specific item by ID.
    
    Args:
        item_id: Item ID
        
    Returns:
        200: Item object
        404: Item not found
    """
    try:
        item = Item.objects.get(id=item_id)
        return JsonResponse(serialize_item(item))
    except Item.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting item {item_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
def api_item_update_put(request, item_id):
    """
    PUT /api/customgpt/items/{item_id}
    
    Update an item (full replacement).
    
    Args:
        item_id: Item ID
        
    Request Body:
        JSON object with item fields
        
    Returns:
        200: Updated Item object
        400: Invalid payload
        404: Item not found
    """
    try:
        item = Item.objects.get(id=item_id)
        
        # Parse request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
        
        # Update fields
        if 'title' in data:
            item.title = data['title']
        if 'description' in data:
            item.description = data['description']
        if 'user_input' in data:
            item.user_input = data['user_input']
        if 'solution_description' in data:
            item.solution_description = data['solution_description']
        if 'status' in data:
            item.status = data['status']
        if 'intern' in data:
            item.intern = data['intern']
        
        # Handle foreign key fields
        if 'type_id' in data and data['type_id']:
            try:
                item.type = ItemType.objects.get(id=data['type_id'])
            except ItemType.DoesNotExist:
                return JsonResponse({'error': 'Invalid type_id'}, status=400)
        
        if 'assigned_to_id' in data:
            if data['assigned_to_id'] is None:
                item.assigned_to = None
            # For simplicity, we don't validate user existence here
            # The model's clean() method will handle validation
        
        # Validate and save
        try:
            item.full_clean()
            item.save()
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)
        
        return JsonResponse(serialize_item(item))
        
    except Item.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    except Exception as e:
        logger.error(f"Error updating item {item_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PATCH"])
def api_item_update_patch(request, item_id):
    """
    PATCH /api/customgpt/items/{item_id}
    
    Update an item (partial update).
    
    Args:
        item_id: Item ID
        
    Request Body:
        JSON object with item fields to update
        
    Returns:
        200: Updated Item object
        400: Invalid payload
        404: Item not found
    """
    # For now, PATCH and PUT behave the same way (partial update)
    return api_item_update_put(request, item_id)


@csrf_exempt
@require_http_methods(["POST"])
def api_project_create_item(request, project_id):
    """
    POST /api/customgpt/projects/{project_id}/items
    
    Create a new item in a project.
    
    Args:
        project_id: Project ID
        
    Request Body:
        JSON object with item fields
        
    Returns:
        201: Created Item object
        400: Invalid payload
        404: Project not found
    """
    try:
        # Verify project exists
        project = Project.objects.get(id=project_id)
        
        # Parse request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
        
        # Validate required fields
        if 'title' not in data:
            return JsonResponse({'error': 'title is required'}, status=400)
        if 'type_id' not in data:
            return JsonResponse({'error': 'type_id is required'}, status=400)
        
        # Get item type
        try:
            item_type = ItemType.objects.get(id=data['type_id'])
        except ItemType.DoesNotExist:
            return JsonResponse({'error': 'Invalid type_id'}, status=400)
        
        # Create item
        item = Item(
            project=project,
            title=data['title'],
            type=item_type,
            description=data.get('description', ''),
            user_input=data.get('user_input', ''),
            solution_description=data.get('solution_description', ''),
            status=data.get('status', ItemStatus.INBOX),
            intern=data.get('intern', False),
        )
        
        # Validate and save
        try:
            item.full_clean()
            item.save()
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)
        
        return JsonResponse(serialize_item(item), status=201)
        
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)
    except Exception as e:
        logger.error(f"Error creating item in project {project_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_item_context(request, item_id):
    """
    GET /api/customgpt/items/{item_id}/context
    
    Get RAG context for an item.
    
    This endpoint uses the existing RAG/AI logic to build context for the item,
    which can be used by CustomGPT for enhanced responses.
    
    Args:
        item_id: Item ID
        
    Returns:
        200: RAG context result as JSON
        404: Item not found
    """
    try:
        # Verify item exists
        item = Item.objects.get(id=item_id)
        
        # Build query from item title and description
        query = f"{item.title} {item.description}".strip()
        
        # Build RAG context using existing service
        context = build_context(
            query=query,
            project_id=str(item.project_id),
            item_id=str(item.id),
            limit=20,
        )
        
        # Return the RAG result 1:1 as JSON
        return JsonResponse(serialize_rag_context(context))
        
    except Item.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting context for item {item_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)
