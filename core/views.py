from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q, Count
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import openai
from google import genai
from django.utils.safestring import mark_safe
import markdown
import bleach
from .models import (
    Project, Item, ItemStatus, ItemComment, User, Release, Node, ItemType, Organisation,
    Attachment, AttachmentLink, AttachmentRole, Activity, ProjectStatus, NodeType, ReleaseStatus,
    AIProvider, AIModel, AIProviderType, AIJobsHistory, UserOrganisation, UserRole,
    ExternalIssueMapping, ExternalIssueKind, Change, ChangeStatus, ChangeApproval, ApprovalStatus, RiskLevel)

from .services.workflow import ItemWorkflowGuard
from .services.activity import ActivityService
from .services.storage import AttachmentStorageService
from .services.agents import AgentService

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
    """Dashboard page view with KPIs and activity overview."""
    from datetime import timedelta
    
    # Calculate KPIs
    kpis = {
        'inbox_count': Item.objects.filter(status=ItemStatus.INBOX).count(),
        'backlog_count': Item.objects.filter(status=ItemStatus.BACKLOG).count(),
        'in_progress_count': Item.objects.filter(
            status__in=[ItemStatus.WORKING, ItemStatus.TESTING, ItemStatus.READY_FOR_RELEASE]
        ).count(),
        'closed_7d_count': Item.objects.filter(
            status=ItemStatus.CLOSED,
            updated_at__gte=timezone.now() - timedelta(days=7)
        ).count(),
        'changes_open_count': Change.objects.exclude(status__in=[ChangeStatus.DEPLOYED, ChangeStatus.CANCELED]).count(),
        'ai_jobs_24h_count': AIJobsHistory.objects.filter(
            timestamp__gte=timezone.now() - timedelta(hours=24)
        ).count(),
    }
    
    # Calculate AI jobs cost (24h)
    ai_jobs_24h = AIJobsHistory.objects.filter(
        timestamp__gte=timezone.now() - timedelta(hours=24),
        costs__isnull=False
    ).aggregate(total_costs=models.Sum('costs'))
    kpis['ai_jobs_24h_costs'] = ai_jobs_24h['total_costs'] or Decimal('0')
    
    context = {
        'kpis': kpis,
    }
    return render(request, 'dashboard.html', context)

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
    """Changes list page view."""
    changes_list = Change.objects.all().select_related(
        'project', 'created_by', 'release'
    ).prefetch_related('approvals__approver')
    
    # Server-side search filter
    q = request.GET.get('q', '')
    if q:
        changes_list = changes_list.filter(
            Q(title__icontains=q) | Q(description__icontains=q)
        )
    
    # Filter by project
    project_filter = request.GET.get('project', '')
    if project_filter:
        try:
            changes_list = changes_list.filter(project_id=int(project_filter))
        except (ValueError, TypeError):
            project_filter = ''
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        changes_list = changes_list.filter(status=status_filter)
    
    # Filter by risk level
    risk_filter = request.GET.get('risk', '')
    if risk_filter:
        changes_list = changes_list.filter(risk=risk_filter)
    
    # Annotate with approval counts
    changes_list = changes_list.annotate(
        total_approvals=Count('approvals'),
        approved_count=Count('approvals', filter=Q(approvals__status=ApprovalStatus.APPROVED)),
        pending_count=Count('approvals', filter=Q(approvals__status=ApprovalStatus.PENDING)),
        rejected_count=Count('approvals', filter=Q(approvals__status=ApprovalStatus.REJECTED))
    )
    
    # Get all projects, statuses and risk levels for filter dropdowns
    projects = Project.objects.all().order_by('name')
    statuses = ChangeStatus.choices
    risk_levels = RiskLevel.choices
    
    context = {
        'changes': changes_list,
        'search_query': q,
        'projects': projects,
        'statuses': statuses,
        'risk_levels': risk_levels,
        'selected_project': project_filter,
        'selected_status': status_filter,
        'selected_risk': risk_filter,
    }
    return render(request, 'changes.html', context)

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
    from core.services.github.service import GitHubService
    
    item = get_object_or_404(Item, id=item_id)
    external_mappings = item.external_mappings.all().order_by('-last_synced_at')
    
    # Check if item can have a GitHub issue created
    github_service = GitHubService()
    can_create_issue = github_service.can_create_issue_for_item(item)
    has_existing_issue = item.external_mappings.filter(kind='Issue').exists()
    
    context = {
        'item': item,
        'external_mappings': external_mappings,
        'can_create_issue': can_create_issue,
        'has_existing_issue': has_existing_issue,
    }
    return render(request, 'partials/item_github_tab.html', context)


@require_POST
def item_link_github(request, item_id):
    """Link a GitHub Issue or Pull Request to an item."""
    from core.services.github.service import GitHubService
    from core.services.github.client import GitHubClient
    
    item = get_object_or_404(Item, id=item_id)
    
    try:
        # Get form data
        github_type = request.POST.get('type', 'Issue')
        number = request.POST.get('number', '').strip()
        
        if not number:
            return HttpResponse("Issue/PR number is required", status=400)
        
        try:
            number = int(number)
        except ValueError:
            return HttpResponse("Issue/PR number must be a valid integer", status=400)
        
        # Initialize GitHub service
        github_service = GitHubService()
        
        if not github_service.is_enabled() or not github_service.is_configured():
            return HttpResponse("GitHub integration is not configured", status=400)
        
        # Get owner and repo from project configuration using service method
        try:
            owner, repo = github_service._get_repo_info(item)
        except ValueError as e:
            return HttpResponse(str(e), status=400)
        
        # Get GitHub client
        client = github_service._get_client()
        
        # Fetch issue or PR data from GitHub
        if github_type == 'Issue':
            github_data = client.get_issue(owner, repo, number)
            kind = ExternalIssueKind.ISSUE
        elif github_type == 'PR':
            github_data = client.get_pr(owner, repo, number)
            kind = ExternalIssueKind.PR
        else:
            return HttpResponse("Invalid type. Must be 'Issue' or 'PR'", status=400)
        
        # Check if mapping already exists
        github_id = github_data['id']
        existing_mapping = ExternalIssueMapping.objects.filter(github_id=github_id).first()
        
        if existing_mapping:
            if existing_mapping.item.id == item.id:
                return HttpResponse("This GitHub item is already linked to this item", status=400)
            else:
                return HttpResponse(f"This GitHub item is already linked to another item: {existing_mapping.item.title}", status=400)
        
        # Create new mapping
        mapping = ExternalIssueMapping.objects.create(
            item=item,
            github_id=github_id,
            number=number,
            kind=kind,
            state=github_data.get('state', 'open'),
            html_url=github_data.get('html_url', f"https://github.com/{owner}/{repo}/issues/{number}"),
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='github.linked',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Linked GitHub {dict(ExternalIssueKind.choices)[kind]} #{number}",
        )
        
        # Return updated GitHub tab
        external_mappings = item.external_mappings.all().order_by('-last_synced_at')
        context = {
            'item': item,
            'external_mappings': external_mappings,
        }
        response = render(request, 'partials/item_github_tab.html', context)
        response['HX-Trigger'] = 'githubLinked'
        return response
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"GitHub linking failed for item {item_id}: {str(e)}")
        return HttpResponse(f"Failed to link GitHub item: {str(e)}", status=500)


@require_POST
def item_create_github_issue(request, item_id):
    """Create a new GitHub issue for an item."""
    from core.services.github.service import GitHubService
    from core.services.integrations.base import IntegrationError
    
    item = get_object_or_404(Item, id=item_id)
    
    try:
        # Initialize GitHub service
        github_service = GitHubService()
        
        # Check if GitHub is enabled and configured
        if not github_service.is_enabled():
            return HttpResponse("GitHub integration is not enabled. Please enable it in GitHub Configuration.", status=400)
        
        if not github_service.is_configured():
            return HttpResponse("GitHub integration is not configured. Please add a GitHub token in GitHub Configuration.", status=400)
        
        # Check if item has valid status
        if not github_service.can_create_issue_for_item(item):
            return HttpResponse(
                f"Cannot create GitHub issue for item with status '{item.status}'. "
                f"Item must have status 'Backlog', 'Working', or 'Testing'.",
                status=400
            )
        
        # Check if item already has a GitHub issue
        if item.external_mappings.filter(kind='Issue').exists():
            return HttpResponse("This item already has a GitHub issue. You can only link existing issues or PRs.", status=400)
        
        # Create GitHub issue
        try:
            mapping = github_service.create_issue_for_item(
                item=item,
                actor=request.user
            )
            
            # Return updated GitHub tab
            external_mappings = item.external_mappings.all().order_by('-last_synced_at')
            context = {
                'item': item,
                'external_mappings': external_mappings,
            }
            response = render(request, 'partials/item_github_tab.html', context)
            response['HX-Trigger'] = 'githubIssueCreated'
            return response
            
        except ValueError as e:
            return HttpResponse(f"Error creating GitHub issue: {str(e)}", status=400)
        except IntegrationError as e:
            return HttpResponse(f"GitHub API error: {str(e)}", status=500)
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"GitHub issue creation failed for item {item_id}: {str(e)}")
        return HttpResponse(f"Failed to create GitHub issue: {str(e)}", status=500)


@require_POST
def item_optimize_description_ai(request, item_id):
    """
    Optimize item description using AI and RAG.
    
    Uses RAG to gather context and then calls the github-issue-creation-agent
    to generate an optimized, machine-readable GitHub issue description.
    
    Only available to users with Agent role.
    """
    from core.services.rag import build_context
    
    # Check user role
    if not request.user.is_authenticated or request.user.role != UserRole.AGENT:
        return JsonResponse({
            'status': 'error',
            'message': 'This feature is only available to users with Agent role'
        }, status=403)
    
    item = get_object_or_404(Item, id=item_id)
    
    try:
        # Get current description
        current_description = item.description or ""
        
        if not current_description.strip():
            return JsonResponse({
                'status': 'error',
                'message': 'Item has no description to optimize'
            }, status=400)
        
        # Build RAG context
        rag_context = build_context(
            query=current_description,
            project_id=str(item.project.id),
            limit=10
        )
        
        # Build input text for agent: description + RAG context
        context_text = rag_context.to_context_text() if rag_context.items else "No additional context found."
        
        agent_input = f"""Original Description:
{current_description}

---
Context from similar items and related information:
{context_text}
"""
        
        # Execute the github-issue-creation-agent
        agent_service = AgentService()
        optimized_description = agent_service.execute_agent(
            filename='github-issue-creation-agent.yml',
            input_text=agent_input,
            user=request.user,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Update item description
        item.description = optimized_description.strip()
        item.save()
        
        # Log activity - success
        activity_service = ActivityService()
        activity_service.log(
            verb='item.description.ai_optimized',
            target=item,
            actor=request.user,
            summary='Item description optimized via AI (RAG + GitHub agent)',
        )
        
        return JsonResponse({
            'status': 'ok'
        })
        
    except Exception as e:
        # Log activity - error
        activity_service = ActivityService()
        activity_service.log(
            verb='item.description.ai_error',
            target=item,
            actor=request.user,
            summary=f'AI description optimization failed: {str(e)}',
        )
        
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"AI description optimization failed for item {item_id}: {str(e)}")
        
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


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
def item_update_comment(request, comment_id):
    """Update a comment."""
    import json
    
    try:
        comment = get_object_or_404(ItemComment, id=comment_id)
        data = json.loads(request.body)
        new_body = data.get('body', '').strip()
        
        if not new_body:
            return JsonResponse({'success': False, 'error': 'Comment body cannot be empty'}, status=400)
        
        comment.body = new_body
        comment.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='comment.updated',
            target=comment.item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Updated comment",
        )
        
        return JsonResponse({'success': True, 'message': 'Comment updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def item_delete_comment(request, comment_id):
    """Delete a comment."""
    try:
        comment = get_object_or_404(ItemComment, id=comment_id)
        item = comment.item
        comment.delete()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='comment.deleted',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Deleted comment",
        )
        
        return JsonResponse({'success': True, 'message': 'Comment deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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
def item_delete_attachment(request, attachment_id):
    """Delete an attachment."""
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        # Get the item for activity logging
        attachment_link = AttachmentLink.objects.filter(attachment=attachment).first()
        if attachment_link and hasattr(attachment_link.target, 'id'):
            item = attachment_link.target
        else:
            item = None
        
        # Mark as deleted
        attachment.is_deleted = True
        attachment.save()
        
        # Log activity
        if item:
            activity_service = ActivityService()
            activity_service.log(
                verb='attachment.deleted',
                target=item,
                actor=request.user if request.user.is_authenticated else None,
                summary=f"Deleted file: {attachment.original_name}",
            )
        
        return JsonResponse({'success': True, 'message': 'Attachment deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def item_view_attachment(request, attachment_id):
    """View an attachment (for viewable file types)."""
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        if attachment.is_deleted:
            return JsonResponse({'success': False, 'error': 'Attachment not found'}, status=404)
        
        # Get file extension
        extension = attachment.original_name.lower().split('.')[-1] if '.' in attachment.original_name else ''
        
        # Read file content
        storage_service = AttachmentStorageService()
        file_content = storage_service.read_attachment(attachment)
        
        # Process based on file type
        if extension == 'md':
            # Render markdown to HTML - create parser instance per request for thread safety
            md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
            html_content = md_parser.convert(file_content.decode('utf-8'))
            # Sanitize HTML
            clean_html = bleach.clean(
                html_content,
                tags=ALLOWED_TAGS,
                attributes=ALLOWED_ATTRIBUTES,
                strip=True
            )
            return JsonResponse({'success': True, 'content_html': clean_html})
        elif extension == 'pdf':
            # Return base64 encoded PDF
            import base64
            pdf_base64 = base64.b64encode(file_content).decode('utf-8')
            return JsonResponse({'success': True, 'content_base64': pdf_base64})
        elif extension in ['html', 'htm']:
            # Return sanitized HTML content (will be displayed in iframe)
            html_content = file_content.decode('utf-8')
            # Sanitize HTML before returning
            clean_html = bleach.clean(
                html_content,
                tags=ALLOWED_TAGS + ['html', 'head', 'body', 'meta', 'title', 'style'],
                attributes=ALLOWED_ATTRIBUTES,
                strip=True
            )
            return JsonResponse({'success': True, 'content': clean_html})
        else:
            # Plain text
            return JsonResponse({'success': True, 'content': file_content.decode('utf-8')})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def item_download_attachment(request, attachment_id):
    """Download an attachment."""
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        if attachment.is_deleted:
            return HttpResponse("Attachment not found", status=404)
        
        # Read file content
        storage_service = AttachmentStorageService()
        file_content = storage_service.read_attachment(attachment)
        
        # Create response with file
        response = HttpResponse(file_content, content_type=attachment.content_type or 'application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{attachment.original_name}"'
        response['Content-Length'] = len(file_content)
        
        return response
    except Exception as e:
        return HttpResponse(f"Download failed: {str(e)}", status=500)


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


@require_POST
def ai_generate_title(request):
    """Generate a title from description using AI agent."""
    import json
    
    try:
        data = json.loads(request.body)
        text = data.get('text', '')
        
        if not text:
            return JsonResponse({'success': False, 'error': 'No text provided'}, status=400)
        
        # Use AgentService to execute the text-to-title-generator agent
        agent_service = AgentService()
        title = agent_service.execute_agent(
            filename='text-to-title-generator.yml',
            input_text=text,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Clean up the title (remove quotes, newlines, etc.)
        title = title.strip().strip('"').strip("'").replace('\n', ' ').replace('\r', '')
        
        return JsonResponse({'success': True, 'title': title})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
def ai_optimize_text(request):
    """Optimize text using AI agent."""
    import json
    
    try:
        data = json.loads(request.body)
        text = data.get('text', '')
        
        if not text:
            return JsonResponse({'success': False, 'error': 'No text provided'}, status=400)
        
        # Use AgentService to execute the text-optimization-agent
        agent_service = AgentService()
        optimized_text = agent_service.execute_agent(
            filename='text-optimization-agent.yml',
            input_text=text,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        return JsonResponse({'success': True, 'text': optimized_text})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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
                    'active': False,  # New models are inactive by default
                    'is_default': False,
                    'input_price_per_1m_tokens': None,
                    'output_price_per_1m_tokens': None,
                }
            )
            if created:
                created_count += 1
            else:
                existing_count += 1
        
        # Return updated models list using the partial template
        models = provider.models.all().order_by('-is_default', 'name')
        context = {
            'provider': provider,
            'models': models,
        }
        return render(request, 'partials/ai_models_list.html', context)
        
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


@require_http_methods(["POST"])
def ai_model_update_field(request, provider_id, model_id):
    """Update a single field of an AI Model via HTMX."""
    provider = get_object_or_404(AIProvider, id=provider_id)
    model = get_object_or_404(AIModel, id=model_id, provider=provider)
    
    try:
        field = request.POST.get('field')
        value = request.POST.get('value', '').strip()
        
        if field in ['input_price_per_1m_tokens', 'output_price_per_1m_tokens']:
            # Validate and convert to Decimal if value is provided
            if value:
                try:
                    decimal_value = Decimal(value)
                    if decimal_value < 0:
                        return HttpResponse("Price cannot be negative", status=400)
                except (InvalidOperation, ValueError):
                    return HttpResponse("Invalid price value", status=400)
                
                if field == 'input_price_per_1m_tokens':
                    model.input_price_per_1m_tokens = decimal_value
                else:
                    model.output_price_per_1m_tokens = decimal_value
            else:
                # Empty value sets to None
                if field == 'input_price_per_1m_tokens':
                    model.input_price_per_1m_tokens = None
                else:
                    model.output_price_per_1m_tokens = None
        else:
            return HttpResponse("Invalid field", status=400)
        
        model.save()
        return HttpResponse(status=200)
        
    except Exception as e:
        return HttpResponse(f"Error updating field: {str(e)}", status=400)


@require_http_methods(["POST"])
def ai_model_toggle_active(request, provider_id, model_id):
    """Toggle the active status of an AI Model via HTMX."""
    provider = get_object_or_404(AIProvider, id=provider_id)
    model = get_object_or_404(AIModel, id=model_id, provider=provider)
    
    try:
        model.active = not model.active
        model.save()
        
        # Return just the updated table row
        context = {
            'provider': provider,
            'model': model,
        }
        return render(request, 'partials/ai_model_row.html', context)
        
    except Exception as e:
        return HttpResponse(f"Error toggling active status: {str(e)}", status=400)


# ==================== Agent Views ====================

def agents(request):
    """Agent list page view."""
    agent_service = AgentService()
    agents_list = agent_service.list_agents()
    
    # Server-side search filter
    q = request.GET.get('q', '')
    if q:
        agents_list = [a for a in agents_list if q.lower() in a.get('name', '').lower() or q.lower() in a.get('description', '').lower()]
    
    # Filter by provider
    provider_filter = request.GET.get('provider', '')
    if provider_filter:
        agents_list = [a for a in agents_list if a.get('provider', '').lower() == provider_filter.lower()]
    
    # Get unique providers for filter dropdown
    providers = sorted(list(set(a.get('provider', 'openai') for a in agent_service.list_agents())))
    
    context = {
        'agents': agents_list,
        'search_query': q,
        'providers': providers,
        'selected_provider': provider_filter,
    }
    return render(request, 'agents.html', context)


def agent_detail(request, filename):
    """Agent detail/edit page view."""
    agent_service = AgentService()
    agent = agent_service.get_agent(filename)
    
    if not agent:
        return HttpResponse("Agent not found", status=404)
    
    # Get all active providers and their models
    providers = AIProvider.objects.filter(active=True).prefetch_related('models')
    provider_types = AIProviderType.choices
    
    context = {
        'agent': agent,
        'is_new': False,
        'providers': providers,
        'provider_types': provider_types,
    }
    return render(request, 'agent_detail.html', context)


def agent_create(request):
    """Agent create page view."""
    # Get all active providers and their models
    providers = AIProvider.objects.filter(active=True).prefetch_related('models')
    provider_types = AIProviderType.choices
    
    context = {
        'agent': {
            'name': '',
            'description': '',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'role': '',
            'task': '',
            'parameters': {},
        },
        'is_new': True,
        'providers': providers,
        'provider_types': provider_types,
    }
    return render(request, 'agent_detail.html', context)


@require_http_methods(["POST"])
def agent_save(request, filename):
    """Save agent (update existing)."""
    agent_service = AgentService()
    
    try:
        # Get form data
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        provider = request.POST.get('provider', 'openai').strip()
        model = request.POST.get('model', 'gpt-3.5-turbo').strip()
        role = request.POST.get('role', '').strip()
        task = request.POST.get('task', '').strip()
        
        # Validate required fields
        if not name:
            return HttpResponse("Agent name is required", status=400)
        
        # Build agent data
        agent_data = {
            'name': name,
            'description': description,
            'provider': provider,
            'model': model,
            'role': role,
            'task': task,
        }
        
        # Parse parameters from form
        parameters = {}
        param_keys = request.POST.getlist('param_key[]')
        param_types = request.POST.getlist('param_type[]')
        param_descriptions = request.POST.getlist('param_description[]')
        param_required = request.POST.getlist('param_required[]')
        
        for i, key in enumerate(param_keys):
            if key.strip():
                param_def = {}
                if i < len(param_types) and param_types[i]:
                    param_def['type'] = param_types[i]
                if i < len(param_descriptions) and param_descriptions[i]:
                    param_def['description'] = param_descriptions[i]
                if i < len(param_required) and param_required[i] == 'true':
                    param_def['required'] = True
                else:
                    param_def['required'] = False
                    
                parameters[key] = param_def
        
        if parameters:
            agent_data['parameters'] = parameters
        
        # Save agent
        agent_service.save_agent(filename, agent_data)
        
        # Redirect to detail view
        return redirect('agent-detail', filename=filename)
        
    except Exception as e:
        return HttpResponse(f"Error saving agent: {str(e)}", status=400)


@require_http_methods(["POST"])
def agent_create_save(request):
    """Save agent (create new)."""
    agent_service = AgentService()
    
    try:
        # Get form data
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        provider = request.POST.get('provider', 'openai').strip()
        model = request.POST.get('model', 'gpt-3.5-turbo').strip()
        role = request.POST.get('role', '').strip()
        task = request.POST.get('task', '').strip()
        
        # Validate required fields
        if not name:
            return HttpResponse("Agent name is required", status=400)
        
        # Build agent data
        agent_data = {
            'name': name,
            'description': description,
            'provider': provider,
            'model': model,
            'role': role,
            'task': task,
        }
        
        # Parse parameters from form
        parameters = {}
        param_keys = request.POST.getlist('param_key[]')
        param_types = request.POST.getlist('param_type[]')
        param_descriptions = request.POST.getlist('param_description[]')
        param_required = request.POST.getlist('param_required[]')
        
        for i, key in enumerate(param_keys):
            if key.strip():
                param_def = {}
                if i < len(param_types) and param_types[i]:
                    param_def['type'] = param_types[i]
                if i < len(param_descriptions) and param_descriptions[i]:
                    param_def['description'] = param_descriptions[i]
                if i < len(param_required) and param_required[i] == 'true':
                    param_def['required'] = True
                else:
                    param_def['required'] = False
                    
                parameters[key] = param_def
        
        if parameters:
            agent_data['parameters'] = parameters
        
        # Creating new agent - generate filename from name
        safe_name = name.lower().replace(' ', '-').replace('_', '-')
        # Remove any non-alphanumeric characters except hyphens
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')
        filename = f"{safe_name}.yml"
        
        # Check if file already exists and add suffix if needed
        counter = 1
        original_filename = filename
        while agent_service.get_agent(filename) is not None:
            name_part = original_filename.replace('.yml', '')
            filename = f"{name_part}-{counter}.yml"
            counter += 1
        
        # Save agent
        agent_service.save_agent(filename, agent_data)
        
        # Redirect to detail view
        return redirect('agent-detail', filename=filename)
        
    except Exception as e:
        return HttpResponse(f"Error saving agent: {str(e)}", status=400)


@require_http_methods(["POST"])
def agent_delete(request, filename):
    """Delete an agent."""
    agent_service = AgentService()
    
    try:
        success = agent_service.delete_agent(filename)
        if not success:
            return HttpResponse("Agent not found", status=404)
        
        # Redirect to agent list
        return redirect('agents')
        
    except Exception as e:
        return HttpResponse(f"Error deleting agent: {str(e)}", status=400)


@require_http_methods(["POST"])
def agent_test(request, filename):
    """Test an agent with input text."""
    agent_service = AgentService()
    
    try:
        # Get input text and parameters from request
        input_text = request.POST.get('input_text', '').strip()
        
        if not input_text:
            return JsonResponse({'error': 'Input text is required'}, status=400)
        
        # Parse parameters if provided
        parameters = {}
        param_keys = request.POST.getlist('test_param_key[]')
        param_values = request.POST.getlist('test_param_value[]')
        
        for i, key in enumerate(param_keys):
            if key.strip() and i < len(param_values):
                parameters[key] = param_values[i]
        
        # Get user and client IP
        user = request.user if request.user.is_authenticated else None
        client_ip = request.META.get('REMOTE_ADDR')
        
        # Execute agent
        result = agent_service.execute_agent(
            filename=filename,
            input_text=input_text,
            user=user,
            client_ip=client_ip,
            parameters=parameters if parameters else None
        )
        
        return JsonResponse({'result': result})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
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


# ============================================================================
# Weaviate Sync Views
# ============================================================================

def weaviate_status(request, object_type, object_id):
    """
    Check Weaviate sync status for an object.
    
    Returns HTML for the Weaviate status button (green if exists, red if not).
    This is an HTMX endpoint that can be called to refresh the button state.
    """
    from core.services.weaviate.client import is_available
    from core.services.weaviate.service import exists_object
    
    # Check if Weaviate is available
    if not is_available():
        return render(request, 'partials/weaviate_button.html', {
            'object_type': object_type,
            'object_id': object_id,
            'exists': False,
            'available': False,
        })
    
    # Check if object exists in Weaviate
    try:
        exists = exists_object(object_type, object_id)
    except Exception as e:
        exists = False
    
    return render(request, 'partials/weaviate_button.html', {
        'object_type': object_type,
        'object_id': object_id,
        'exists': exists,
        'available': True,
    })


def weaviate_object(request, object_type, object_id):
    """
    Fetch Weaviate object data and display in modal content.
    
    Returns HTML for the modal body showing either:
    - The Weaviate object as formatted JSON (if exists)
    - A message with a "Push to Weaviate" button (if not exists)
    """
    from core.services.weaviate.client import is_available
    from core.services.weaviate.service import fetch_object_by_type
    import json
    
    # Check if Weaviate is available
    if not is_available():
        return render(request, 'partials/weaviate_modal_content.html', {
            'object_type': object_type,
            'object_id': object_id,
            'available': False,
            'error': 'Weaviate service is not configured or disabled.',
        })
    
    # Fetch object from Weaviate
    try:
        obj_data = fetch_object_by_type(object_type, object_id)
        
        if obj_data:
            # Format as pretty JSON
            json_str = json.dumps(obj_data, indent=2, default=str)
            
            return render(request, 'partials/weaviate_modal_content.html', {
                'object_type': object_type,
                'object_id': object_id,
                'available': True,
                'exists': True,
                'json_data': json_str,
            })
        else:
            return render(request, 'partials/weaviate_modal_content.html', {
                'object_type': object_type,
                'object_id': object_id,
                'available': True,
                'exists': False,
            })
            
    except Exception as e:
        return render(request, 'partials/weaviate_modal_content.html', {
            'object_type': object_type,
            'object_id': object_id,
            'available': True,
            'error': str(e),
        })


@require_POST
def weaviate_push(request, object_type, object_id):
    """
    Manually push an object to Weaviate.
    
    This endpoint performs a manual sync of the object to Weaviate.
    Returns updated modal content showing the synced object.
    """
    from core.services.weaviate.client import is_available
    from core.services.weaviate.service import upsert_object
    import json
    
    # Check if Weaviate is available
    if not is_available():
        return render(request, 'partials/weaviate_modal_content.html', {
            'object_type': object_type,
            'object_id': object_id,
            'available': False,
            'error': 'Weaviate service is not configured or disabled.',
        })
    
    # Push object to Weaviate
    try:
        uuid_str = upsert_object(object_type, object_id)
        
        if uuid_str:
            # Fetch the newly created object to show it
            from core.services.weaviate.service import fetch_object_by_type
            obj_data = fetch_object_by_type(object_type, object_id)
            
            if obj_data:
                json_str = json.dumps(obj_data, indent=2, default=str)
                
                return render(request, 'partials/weaviate_modal_content.html', {
                    'object_type': object_type,
                    'object_id': object_id,
                    'available': True,
                    'exists': True,
                    'json_data': json_str,
                    'success_message': 'Successfully pushed to Weaviate!',
                })
            else:
                return render(request, 'partials/weaviate_modal_content.html', {
                    'object_type': object_type,
                    'object_id': object_id,
                    'available': True,
                    'exists': True,
                    'success_message': 'Successfully pushed to Weaviate!',
                })
        else:
            return render(request, 'partials/weaviate_modal_content.html', {
                'object_type': object_type,
                'object_id': object_id,
                'available': True,
                'error': 'Could not push object to Weaviate. Object type may not be supported.',
            })
            
    except Exception as e:
        return render(request, 'partials/weaviate_modal_content.html', {
            'object_type': object_type,
            'object_id': object_id,
            'available': True,
            'error': f'Error pushing to Weaviate: {str(e)}',
        })


# Change Management Views

def change_detail(request, id):
    """Change detail page view."""
    change = get_object_or_404(
        Change.objects.select_related(
            'project', 'created_by', 'release'
        ).prefetch_related('approvals__approver'),
        id=id
    )
    
    # Render markdown fields to HTML with sanitization
    description_html = None
    if change.description:
        MARKDOWN_PARSER.reset()
        html = MARKDOWN_PARSER.convert(change.description)
        description_html = mark_safe(bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True))
    
    risk_description_html = None
    if change.risk_description:
        MARKDOWN_PARSER.reset()
        html = MARKDOWN_PARSER.convert(change.risk_description)
        risk_description_html = mark_safe(bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True))
    
    mitigation_html = None
    if change.mitigation:
        MARKDOWN_PARSER.reset()
        html = MARKDOWN_PARSER.convert(change.mitigation)
        mitigation_html = mark_safe(bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True))
    
    rollback_plan_html = None
    if change.rollback_plan:
        MARKDOWN_PARSER.reset()
        html = MARKDOWN_PARSER.convert(change.rollback_plan)
        rollback_plan_html = mark_safe(bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True))
    
    communication_plan_html = None
    if change.communication_plan:
        MARKDOWN_PARSER.reset()
        html = MARKDOWN_PARSER.convert(change.communication_plan)
        communication_plan_html = mark_safe(bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True))
    
    # Get all users for approver selection
    all_users = User.objects.filter(active=True).order_by('name')
    
    # Get items associated with this change
    items = change.items.all().select_related('project', 'type')
    
    context = {
        'change': change,
        'description_html': description_html,
        'risk_description_html': risk_description_html,
        'mitigation_html': mitigation_html,
        'rollback_plan_html': rollback_plan_html,
        'communication_plan_html': communication_plan_html,
        'all_users': all_users,
        'items': items,
    }
    return render(request, 'change_detail.html', context)


def change_create(request):
    """Change create page view."""
    if request.method == 'GET':
        # Show the create form
        projects = Project.objects.all().order_by('name')
        statuses = ChangeStatus.choices
        risk_levels = RiskLevel.choices
        releases = Release.objects.all().select_related('project').order_by('-update_date')
        
        context = {
            'change': None,
            'projects': projects,
            'statuses': statuses,
            'risk_levels': risk_levels,
            'releases': releases,
        }
        return render(request, 'change_form.html', context)
    
    # Handle POST request
    try:
        project_id = request.POST.get('project')
        if not project_id:
            if request.headers.get('HX-Request'):
                return JsonResponse({'success': False, 'error': 'Project is required'}, status=400)
            else:
                # Regular form submission - re-render form with error
                projects = Project.objects.all().order_by('name')
                statuses = ChangeStatus.choices
                risk_levels = RiskLevel.choices
                releases = Release.objects.all().select_related('project').order_by('-update_date')
                context = {
                    'change': None,
                    'projects': projects,
                    'statuses': statuses,
                    'risk_levels': risk_levels,
                    'releases': releases,
                    'error': 'Project is required'
                }
                return render(request, 'change_form.html', context)
        
        project = get_object_or_404(Project, id=project_id)
        
        # Get release if provided
        release = None
        release_id = request.POST.get('release')
        if release_id:
            release = get_object_or_404(Release, id=release_id)
        
        # Parse datetime fields
        planned_start = request.POST.get('planned_start')
        planned_end = request.POST.get('planned_end')
        executed_at = request.POST.get('executed_at')
        
        change = Change.objects.create(
            project=project,
            title=request.POST.get('title'),
            description=request.POST.get('description', ''),
            planned_start=planned_start if planned_start else None,
            planned_end=planned_end if planned_end else None,
            executed_at=executed_at if executed_at else None,
            status=request.POST.get('status', ChangeStatus.DRAFT),
            risk=request.POST.get('risk', RiskLevel.NORMAL),
            risk_description=request.POST.get('risk_description', ''),
            mitigation=request.POST.get('mitigation', ''),
            rollback_plan=request.POST.get('rollback_plan', ''),
            communication_plan=request.POST.get('communication_plan', ''),
            release=release,
            created_by=request.user if request.user.is_authenticated else None,
        )
        
        # Log activity
        ActivityService.log_activity(
            target=change,
            verb='created',
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Change "{change.title}" was created'
        )
        
        # Return JSON for HTMX requests, redirect for regular requests
        if request.headers.get('HX-Request'):
            return JsonResponse({
                'success': True,
                'message': 'Change created successfully',
                'change_id': change.id,
                'redirect': f'/changes/{change.id}/'
            })
        else:
            return redirect('change-detail', id=change.id)
    except Exception as e:
        if request.headers.get('HX-Request'):
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        else:
            projects = Project.objects.all().order_by('name')
            statuses = ChangeStatus.choices
            risk_levels = RiskLevel.choices
            releases = Release.objects.all().select_related('project').order_by('-update_date')
            context = {
                'change': None,
                'projects': projects,
                'statuses': statuses,
                'risk_levels': risk_levels,
                'releases': releases,
                'error': str(e)
            }
            return render(request, 'change_form.html', context)


def change_edit(request, id):
    """Change edit page view."""
    change = get_object_or_404(Change, id=id)
    
    if request.method == 'GET':
        # Show the edit form
        projects = Project.objects.all().order_by('name')
        statuses = ChangeStatus.choices
        risk_levels = RiskLevel.choices
        releases = Release.objects.filter(project=change.project).order_by('-update_date')
        
        context = {
            'change': change,
            'projects': projects,
            'statuses': statuses,
            'risk_levels': risk_levels,
            'releases': releases,
        }
        return render(request, 'change_form.html', context)


@require_http_methods(["POST"])
def change_update(request, id):
    """Update change details."""
    change = get_object_or_404(Change, id=id)
    
    try:
        # Update basic fields
        change.title = request.POST.get('title', change.title)
        change.description = request.POST.get('description', change.description)
        change.status = request.POST.get('status', change.status)
        change.risk = request.POST.get('risk', change.risk)
        change.risk_description = request.POST.get('risk_description', change.risk_description)
        change.mitigation = request.POST.get('mitigation', change.mitigation)
        change.rollback_plan = request.POST.get('rollback_plan', change.rollback_plan)
        change.communication_plan = request.POST.get('communication_plan', change.communication_plan)
        
        # Update project if changed
        project_id = request.POST.get('project')
        if project_id and int(project_id) != change.project.id:
            change.project = get_object_or_404(Project, id=project_id)
        
        # Update release if provided
        release_id = request.POST.get('release')
        if release_id:
            change.release = get_object_or_404(Release, id=release_id)
        else:
            change.release = None
        
        # Parse datetime fields
        planned_start = request.POST.get('planned_start')
        planned_end = request.POST.get('planned_end')
        executed_at = request.POST.get('executed_at')
        
        change.planned_start = planned_start if planned_start else None
        change.planned_end = planned_end if planned_end else None
        change.executed_at = executed_at if executed_at else None
        
        change.save()
        
        # Log activity
        ActivityService.log_activity(
            target=change,
            verb='updated',
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Change "{change.title}" was updated'
        )
        
        return JsonResponse({'success': True, 'message': 'Change updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def change_delete(request, id):
    """Delete a change."""
    change = get_object_or_404(Change, id=id)
    
    try:
        title = change.title
        change.delete()
        
        # Log activity - note: can't log to deleted object, so we skip this
        
        return JsonResponse({'success': True, 'redirect': '/changes/'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def change_add_approver(request, id):
    """Add an approver to a change."""
    change = get_object_or_404(Change, id=id)
    user_id = request.POST.get('user_id')
    is_required = request.POST.get('is_required', 'true').lower() == 'true'
    
    if not user_id:
        return JsonResponse({'success': False, 'error': 'User ID required'}, status=400)
    
    try:
        user = get_object_or_404(User, id=user_id)
        
        # Check if approver already exists
        if ChangeApproval.objects.filter(change=change, approver=user).exists():
            return JsonResponse({'success': False, 'error': 'Approver already exists'}, status=400)
        
        approval = ChangeApproval.objects.create(
            change=change,
            approver=user,
            is_required=is_required,
            status=ApprovalStatus.PENDING
        )
        
        # Log activity
        ActivityService.log_activity(
            target=change,
            verb='added_approver',
            actor=request.user if request.user.is_authenticated else None,
            summary=f'{user.name} was added as an approver'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Approver added successfully',
            'reload': True
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def change_remove_approver(request, id, approval_id):
    """Remove an approver from a change."""
    change = get_object_or_404(Change, id=id)
    approval = get_object_or_404(ChangeApproval, id=approval_id, change=change)
    
    try:
        approver_name = approval.approver.name
        approval.delete()
        
        # Log activity
        ActivityService.log_activity(
            target=change,
            verb='removed_approver',
            actor=request.user if request.user.is_authenticated else None,
            summary=f'{approver_name} was removed as an approver'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Approver removed successfully',
            'reload': True
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def change_approve(request, id, approval_id):
    """Approve a change."""
    change = get_object_or_404(Change, id=id)
    approval = get_object_or_404(ChangeApproval, id=approval_id, change=change)
    
    try:
        approval.status = ApprovalStatus.APPROVED
        approval.decision_at = timezone.now()
        approval.comment = request.POST.get('comment', '')
        approval.save()
        
        # Log activity
        ActivityService.log_activity(
            target=change,
            verb='approved',
            actor=request.user if request.user.is_authenticated else None,
            summary=f'{approval.approver.name} approved the change'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Change approved successfully',
            'reload': True
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_http_methods(["POST"])
def change_reject(request, id, approval_id):
    """Reject a change."""
    change = get_object_or_404(Change, id=id)
    approval = get_object_or_404(ChangeApproval, id=approval_id, change=change)
    
    try:
        approval.status = ApprovalStatus.REJECTED
        approval.decision_at = timezone.now()
        approval.comment = request.POST.get('comment', '')
        approval.save()
        
        # Log activity
        ActivityService.log_activity(
            target=change,
            verb='rejected',
            actor=request.user if request.user.is_authenticated else None,
            summary=f'{approval.approver.name} rejected the change'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Change rejected',
            'reload': True
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def get_human_readable_verb(verb):
    """Convert activity verb to human-readable text."""
    verb_mapping = {
        # Items
        'item.created': 'Item created',
        'item.status_changed': 'Status changed',
        'item.assigned': 'Item assigned',
        'item.updated': 'Item updated',
        
        # Projects
        'project.created': 'Project created',
        'project.status_changed': 'Project status changed',
        'project.updated': 'Project updated',
        
        # GitHub
        'github.issue_created': 'GitHub issue created',
        'github.pr_created': 'GitHub PR created',
        'github.mapping_synced': 'GitHub mapping synced',
        'github.linked': 'GitHub linked',
        
        # Comments
        'comment.added': 'Comment added',
        'comment.updated': 'Comment updated',
        'comment.deleted': 'Comment deleted',
        
        # Attachments
        'attachment.uploaded': 'Attachment uploaded',
        'attachment.deleted': 'Attachment deleted',
        
        # Changes
        'change.created': 'Change created',
        'change.status_changed': 'Change status changed',
        'change.approved': 'Change approved',
        'change.rejected': 'Change rejected',
        
        # AI
        'ai.job_completed': 'AI job completed',
        'ai.job_failed': 'AI job failed',
        
        # Graph API
        'graph.mail_sent': 'Email sent',
        
        # Default fallback
        'created': 'Created',
        'updated': 'Updated',
        'deleted': 'Deleted',
        'approved': 'Approved',
        'rejected': 'Rejected',
    }
    
    return verb_mapping.get(verb, verb.replace('_', ' ').replace('.', ' ').title())


def dashboard_in_progress_items(request):
    """HTMX partial for in-progress items list."""
    items = Item.objects.filter(
        status__in=[ItemStatus.WORKING, ItemStatus.TESTING, ItemStatus.READY_FOR_RELEASE]
    ).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-updated_at')[:20]
    
    context = {
        'items': items,
    }
    return render(request, 'partials/dashboard_in_progress.html', context)


def dashboard_activity_stream(request):
    """HTMX partial for global activity stream."""
    from django.utils.timesince import timesince
    
    # Get filter parameter
    filter_type = request.GET.get('filter', 'all')
    offset = int(request.GET.get('offset', 0))
    limit = 50
    
    # Base queryset
    activity_service = ActivityService()
    activities = Activity.objects.select_related('actor', 'target_content_type').order_by('-created_at')
    
    # Apply filter
    if filter_type and filter_type != 'all':
        if filter_type == 'items':
            item_ct = ContentType.objects.get_for_model(Item)
            activities = activities.filter(target_content_type=item_ct)
        elif filter_type == 'projects':
            project_ct = ContentType.objects.get_for_model(Project)
            activities = activities.filter(target_content_type=project_ct)
        elif filter_type == 'github':
            activities = activities.filter(verb__startswith='github.')
        elif filter_type == 'changes':
            change_ct = ContentType.objects.get_for_model(Change)
            activities = activities.filter(target_content_type=change_ct)
        elif filter_type == 'ai':
            activities = activities.filter(verb__startswith='ai.')
    
    # Paginate
    activities = activities[offset:offset + limit]
    
    # Build activity list with human-readable verbs and relative times
    activity_list = []
    for activity in activities:
        # Get target URL if possible
        target_url = None
        target_title = None
        if activity.target_content_type.model == 'item' and activity.target_object_id:
            try:
                item = Item.objects.get(id=activity.target_object_id)
                target_url = f'/items/{item.id}/'
                target_title = item.title
            except Item.DoesNotExist:
                pass
        elif activity.target_content_type.model == 'project' and activity.target_object_id:
            try:
                project = Project.objects.get(id=activity.target_object_id)
                target_url = f'/projects/{project.id}/'
                target_title = project.name
            except Project.DoesNotExist:
                pass
        elif activity.target_content_type.model == 'change' and activity.target_object_id:
            try:
                change = Change.objects.get(id=activity.target_object_id)
                target_url = f'/changes/{change.id}/'
                target_title = change.title
            except Change.DoesNotExist:
                pass
        
        activity_list.append({
            'id': activity.id,
            'verb': get_human_readable_verb(activity.verb),
            'actor': activity.actor,
            'summary': activity.summary,
            'created_at': activity.created_at,
            'time_ago': timesince(activity.created_at),
            'target_url': target_url,
            'target_title': target_title,
        })
    
    context = {
        'activities': activity_list,
        'filter_type': filter_type,
        'offset': offset,
        'limit': limit,
        'has_more': len(activities) == limit,
        'next_offset': offset + limit,
    }
    return render(request, 'partials/dashboard_activity_stream.html', context)
