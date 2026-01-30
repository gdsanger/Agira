from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, Http404
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction, IntegrityError
from django.db.models import Q, Count
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.urls import reverse
from django.conf import settings
from decimal import Decimal, InvalidOperation
import logging
import os
import re
import json
import openai
from google import genai
from django.utils.safestring import mark_safe
import markdown
import bleach
from .models import (
    Project, Item, ItemStatus, ItemComment, User, Release, Node, ItemType, Organisation,
    Attachment, AttachmentLink, AttachmentRole, Activity, ProjectStatus, NodeType, ReleaseStatus,
    AIProvider, AIModel, AIProviderType, AIJobsHistory, UserOrganisation, UserRole,
    ExternalIssueMapping, ExternalIssueKind, Change, ChangeStatus, ChangeApproval, ApprovalStatus, RiskLevel, ReleaseType,
    MailTemplate, MailActionMapping)

from .services.workflow import ItemWorkflowGuard
from .services.activity import ActivityService
from .services.storage import AttachmentStorageService
from .services.agents import AgentService
from .services.mail import check_mail_trigger, prepare_mail_preview
from .backends.azuread import AzureADAuth, AzureADAuthError

# Configure logging
logger = logging.getLogger(__name__)

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

def login_view(request):
    """Login page view."""
    # If user is already authenticated, redirect to dashboard
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        next_url = request.POST.get('next', 'dashboard')
        
        # Authenticate user
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if user.active:
                # Login the user
                auth_login(request, user)
                # Redirect to next page or dashboard
                return redirect(next_url if next_url else 'dashboard')
            else:
                # User account is inactive
                error = 'Ihr Konto ist deaktiviert.'
                return render(request, 'login.html', {
                    'error': error, 
                    'next': next_url,
                    'azure_ad_enabled': settings.AZURE_AD_ENABLED
                })
        else:
            # Invalid credentials
            error = 'Benutzername oder Passwort ist falsch.'
            return render(request, 'login.html', {
                'error': error, 
                'next': next_url,
                'azure_ad_enabled': settings.AZURE_AD_ENABLED
            })
    
    # GET request - show login form
    next_url = request.GET.get('next', '')
    return render(request, 'login.html', {
        'next': next_url,
        'azure_ad_enabled': settings.AZURE_AD_ENABLED
    })

def logout_view(request):
    """Logout view with Azure AD single sign-out support."""
    # Check if user was logged in via Azure AD (has azure_ad_object_id)
    azure_ad_user = False
    if request.user.is_authenticated:
        azure_ad_user = hasattr(request.user, 'azure_ad_object_id') and request.user.azure_ad_object_id
    
    # Log out from Agira
    auth_logout(request)
    
    # If user was logged in via Azure AD and Azure AD is enabled, offer single logout
    if azure_ad_user and settings.AZURE_AD_ENABLED:
        # Redirect to Azure AD logout
        try:
            azure_ad = AzureADAuth()
            post_logout_uri = request.build_absolute_uri(reverse('login'))
            logout_url = azure_ad.get_logout_url(post_logout_uri)
            return redirect(logout_url)
        except AzureADAuthError as e:
            logger.warning(f"Azure AD logout failed: {str(e)}")
            # Continue with local logout page
        except Exception as e:
            logger.error(f"Unexpected error during Azure AD logout: {str(e)}", exc_info=True)
            # Continue with local logout page
    
    return render(request, 'logged_out.html')

@login_required
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

@login_required
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

@login_required
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

@login_required
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

@login_required
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
    
    # Count attachments for this project
    content_type = ContentType.objects.get_for_model(Project)
    attachments_count = AttachmentLink.objects.filter(
        target_content_type=content_type,
        target_object_id=project.id,
        role=AttachmentRole.PROJECT_FILE,
        attachment__is_deleted=False
    ).count()
    
    context = {
        'project': project,
        'description_html': description_html,
        'all_organisations': all_organisations,
        'item_types': item_types,
        'node_types': node_types,
        'attachments_count': attachments_count,
    }
    return render(request, 'project_detail.html', context)

@login_required
def project_items_tab(request, id):
    """Project Items tab with pagination, filtering, and sorting."""
    project = get_object_or_404(Project, id=id)
    
    # Start with all items for this project
    items = Item.objects.filter(project=project).select_related(
        'type', 'assigned_to'
    ).order_by('-updated_at')
    
    # Get filter parameters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.getlist('status')
    type_filter = request.GET.getlist('type')
    
    # Convert type_filter to integers for proper comparison
    type_filter_ints = []
    for t in type_filter:
        try:
            type_filter_ints.append(int(t))
        except (ValueError, TypeError):
            pass
    
    # Apply search filter (title and description)
    if search_query:
        items = items.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        items = items.filter(status__in=status_filter)
    
    # Apply type filter
    if type_filter_ints:
        items = items.filter(type_id__in=type_filter_ints)
    
    # Pagination - 25 items per page
    paginator = Paginator(items, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Get all item types for filter dropdown
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    
    # Get all status choices
    status_choices = ItemStatus.choices
    
    context = {
        'project': project,
        'page_obj': page_obj,
        'search_query': search_query,
        'selected_statuses': status_filter,
        'selected_types': type_filter_ints,
        'item_types': item_types,
        'status_choices': status_choices,
        'closed_status_value': ItemStatus.CLOSED,  # Pass the constant to template
    }
    return render(request, 'partials/project_items_tab.html', context)

@login_required
def items_inbox(request):
    """Items Inbox page view."""
    items = Item.objects.filter(status=ItemStatus.INBOX).select_related(
        'project', 'type', 'organisation', 'requester', 'assigned_to'
    ).order_by('-created_at')
    
    context = {
        'items': items,
    }
    return render(request, 'items_inbox.html', context)

@login_required
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

@login_required
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

@login_required
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

@login_required
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

@login_required
def items_planning(request):
    """Items Planning page view."""
    items = Item.objects.filter(status=ItemStatus.PLANING).select_related(
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
    return render(request, 'items_planning.html', context)

@login_required
def items_specification(request):
    """Items Specification page view."""
    items = Item.objects.filter(status=ItemStatus.SPECIFICATION).select_related(
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
    return render(request, 'items_specification.html', context)

def get_open_github_issues_count():
    """
    Get count of open GitHub issues linked to items with status Working or Testing.
    
    Returns:
        int: Count of open GitHub issues (excluding PRs, excluding closed issues)
    """
    return ExternalIssueMapping.objects.filter(
        item__status__in=[ItemStatus.WORKING, ItemStatus.TESTING],
        kind=ExternalIssueKind.ISSUE,
    ).exclude(
        state='closed'
    ).count()

@login_required
def items_github_open(request):
    """Open GitHub Issues page view - shows all open GitHub issues linked to Working/Testing items."""
    # Query ExternalIssueMapping directly to get all open issues from Working/Testing items
    # This avoids N+1 queries and correctly handles items with multiple mappings
    open_issue_mappings = ExternalIssueMapping.objects.filter(
        item__status__in=[ItemStatus.WORKING, ItemStatus.TESTING],
        kind=ExternalIssueKind.ISSUE,
    ).exclude(
        state='closed'
    ).select_related('item', 'item__project').order_by('-number')
    
    # Build list of issue data for display
    issues_data = []
    for mapping in open_issue_mappings:
        issues_data.append({
            'issue_number': mapping.number,
            'item_title': mapping.item.title,
            'item_id': mapping.item.id,
            'github_url': mapping.html_url,
        })
    
    context = {
        'issues_data': issues_data,
    }
    return render(request, 'items_github_open.html', context)

@login_required
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

@login_required
def item_lookup(request, item_id):
    """
    Lightweight endpoint to check if an issue exists and is accessible.
    Returns JSON with status information.
    Used by the header Issue ID search feature.
    
    Note: This view currently follows the same authorization model as item_detail,
    which allows any authenticated user to access any item. If more granular
    permissions are implemented in the future, they should be added here as well.
    """
    try:
        # Use select_related to minimize queries, similar to item_detail
        item = Item.objects.select_related('project').get(id=item_id)
        return JsonResponse({
            'exists': True,
            'id': item.id,
        })
    except Item.DoesNotExist:
        return JsonResponse({
            'exists': False,
            'error': 'Es existiert kein Issue mit dieser ID.',
        }, status=404)

@login_required
def item_detail(request, item_id):
    """Item detail page with tabs."""
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release'
        ).prefetch_related('nodes'),
        id=item_id
    )
    
    # Get followers for this item
    followers = item.get_followers()
    
    # Get all users for the follower selection dropdown
    users = User.objects.all().order_by('name')
    
    # Get all projects for the move modal
    projects = Project.objects.all().order_by('name')
    
    # Get initial tab from query parameter (default: overview)
    active_tab = request.GET.get('tab', 'overview')
    
    context = {
        'item': item,
        'followers': followers,
        'users': users,
        'projects': projects,
        'active_tab': active_tab,
        'available_statuses': ItemStatus.choices,
    }
    return render(request, 'item_detail.html', context)


@login_required
def item_comments_tab(request, item_id):
    """HTMX endpoint to load comments tab."""
    item = get_object_or_404(Item, id=item_id)
    comments = item.comments.select_related('author').order_by('-created_at')
    
    context = {
        'item': item,
        'comments': comments,
    }
    return render(request, 'partials/item_comments_tab.html', context)


@login_required
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


@login_required
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


@login_required
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


@login_required

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


@login_required

@require_POST
def item_create_github_issue(request, item_id):
    """Create a new GitHub issue for an item."""
    from core.services.github.service import GitHubService
    from core.services.integrations.base import IntegrationError
    from core.services.mail import check_mail_trigger, prepare_mail_preview
    
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
        
        # Check if this is a follow-up issue (item already has issues)
        existing_issues = item.external_mappings.filter(kind='Issue').exists()
        
        if existing_issues:
            # For follow-up issues, get the notes from the request
            notes = request.POST.get('notes', '').strip()
            
            if not notes:
                return HttpResponse("Notes are required for creating a follow-up issue.", status=400)
            
            # Update item description BEFORE creating GitHub issue
            # This ensures the notes and existing issue references are included in the GitHub issue body
            _append_followup_notes_to_item(item, notes)
        
        # Store old status to detect changes
        old_status = item.status
        
        # Create GitHub issue (this will also change status to WORKING if applicable)
        try:
            mapping = github_service.create_issue_for_item(
                item=item,
                actor=request.user
            )
            
            # For follow-up issues, update the references section to include the newly created issue
            if existing_issues:
                _update_issue_references(item)
            
            # Check if status changed and if mail trigger exists
            # Refresh item to get the latest status
            item.refresh_from_db()
            status_changed = (old_status != item.status)
            
            # Check for mail trigger if status changed
            if status_changed:
                mapping = check_mail_trigger(item)
                if mapping:
                    # Prepare mail preview for modal
                    mail_preview = prepare_mail_preview(item, mapping)
                    
                    # Return JSON response with mail preview and updated tab HTML
                    external_mappings = item.external_mappings.all().order_by('-last_synced_at')
                    can_create_issue = github_service.can_create_issue_for_item(item)
                    has_existing_issue = item.external_mappings.filter(kind='Issue').exists()
                    
                    context = {
                        'item': item,
                        'external_mappings': external_mappings,
                        'can_create_issue': can_create_issue,
                        'has_existing_issue': has_existing_issue,
                    }
                    
                    # Render the GitHub tab to HTML string
                    from django.template.loader import render_to_string
                    github_tab_html = render_to_string('partials/item_github_tab.html', context, request=request)
                    
                    # Return JSON with both mail preview and tab HTML
                    return JsonResponse({
                        'success': True,
                        'mail_preview': mail_preview,
                        'github_tab_html': github_tab_html,
                        'item_id': item.id
                    })
            
            # No mail trigger or no status change - return updated GitHub tab
            external_mappings = item.external_mappings.all().order_by('-last_synced_at')
            can_create_issue = github_service.can_create_issue_for_item(item)
            has_existing_issue = item.external_mappings.filter(kind='Issue').exists()
            
            context = {
                'item': item,
                'external_mappings': external_mappings,
                'can_create_issue': can_create_issue,
                'has_existing_issue': has_existing_issue,
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


def _append_followup_notes_to_item(item, notes):
    """
    Append follow-up notes and issue/PR references to item description.
    
    This function is called BEFORE the new GitHub issue is created to ensure
    the notes and existing issue references are included in the GitHub issue body.
    After creation, _update_issue_references() is called to add the new issue number.
    
    Args:
        item: Item instance
        notes: User-provided notes for the follow-up
    """
    from datetime import datetime
    
    # Get current date formatted for German locale
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    # Get existing issue and PR numbers
    mappings = item.external_mappings.all().order_by('kind', 'number')
    issue_pr_refs = ", ".join([f"#{m.number}" for m in mappings])
    
    # Build the addition to description
    addition_parts = []
    
    # Initialize description if it's None or empty
    if not item.description:
        item.description = ""
    
    # If description doesn't have original header, add it
    if item.description and not item.description.startswith("## "):
        # Preserve original description with header
        original_desc = item.description
        item.description = f"## Original Item Issue Text\n{original_desc}"
    
    # Add notes section
    addition_parts.append(f"\n\n## Hinweise und Änderungen {current_date}")
    addition_parts.append(notes)
    
    # Add issue/PR references section
    if issue_pr_refs:
        addition_parts.append("\n### Siehe folgende Issues und PRs")
        addition_parts.append(issue_pr_refs)
    
    # Append to description
    item.description += "\n".join(addition_parts)
    item.save(update_fields=['description'])


def _update_issue_references(item):
    """
    Update the issue/PR references section in the item description to include
    all current mappings (including newly created ones).
    
    This is called AFTER a new GitHub issue has been created to add its number
    to the references list.
    
    Args:
        item: Item instance
    """
    import re
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Refresh item to get the latest description
    item.refresh_from_db()
    
    # Get all issue and PR numbers
    mappings = item.external_mappings.all().order_by('kind', 'number')
    issue_pr_refs = ", ".join([f"#{m.number}" for m in mappings])
    
    if not issue_pr_refs:
        logger.warning(f"No issue/PR references found for item {item.id}, but _update_issue_references was called")
        return
    
    # Find and replace the references section
    # Pattern matches the header followed by the references on the next line(s)
    # This handles cases where there might be whitespace or multiple lines of refs
    pattern = r"(### Siehe folgende Issues und PRs\s*\n)([^\n#]*)"
    replacement = rf"\g<1>{issue_pr_refs}"
    
    if re.search(pattern, item.description):
        item.description = re.sub(pattern, replacement, item.description)
        item.save(update_fields=['description'])
    else:
        logger.warning(
            f"Could not find 'Siehe folgende Issues und PRs' section in item {item.id} description. "
            f"The newly created issue may not be added to references."
        )


@login_required

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


@login_required
@require_POST
def item_generate_solution_ai(request, item_id):
    """
    Generate solution description using AI and RAG.
    
    Uses RAG to gather context and then calls the create-user-description agent
    to generate a solution description based on the item description.
    
    Only available to users with Agent role.
    """
    from core.services.rag import build_context
    
    # Check user role
    if request.user.role != UserRole.AGENT:
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
                'message': 'Item has no description. Please provide a description first.'
            }, status=400)
        
        # Build RAG context
        rag_context = build_context(
            query=current_description,
            project_id=str(item.project.id),
            limit=10
        )
        
        # Build input text for agent: description + RAG context
        context_text = rag_context.to_context_text() if rag_context.items else "No additional context found."
        
        agent_input = f"""Item Description:
{current_description}

---
Context from similar items and related information:
{context_text}
"""
        
        # Execute the create-user-description agent
        agent_service = AgentService()
        solution_description = agent_service.execute_agent(
            filename='create-user-description.yml',
            input_text=agent_input,
            user=request.user,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Update item solution_description
        item.solution_description = solution_description.strip()
        item.save(update_fields=['solution_description'])
        
        # Log activity - success
        activity_service = ActivityService()
        activity_service.log(
            verb='item.solution_description.ai_generated',
            target=item,
            actor=request.user,
            summary='Solution description generated via AI (RAG + create-user-description agent)',
        )
        
        return JsonResponse({
            'status': 'ok'
        })
        
    except Exception as e:
        # Log activity - error
        activity_service = ActivityService()
        activity_service.log(
            verb='item.solution_description.ai_error',
            target=item,
            actor=request.user,
            summary=f'AI solution description generation failed: {str(e)}',
        )
        
        logger.error(f"AI solution description generation failed for item {item_id}: {str(e)}")
        
        return JsonResponse({
            'status': 'error',
            'message': 'Failed to generate solution description. Please try again later.'
        }, status=500)


@login_required
@require_POST
def item_pre_review(request, item_id):
    """
    Generate a Pre-Review of an item using AI and RAG.
    
    Uses RAG to gather context and then calls the issue-analyse-agent
    to generate a comprehensive review with recommendations.
    
    Only available to users with Agent role.
    """
    import json
    from core.services.rag import build_context
    
    # Check user role
    if not request.user.is_authenticated or request.user.role != UserRole.AGENT:
        return JsonResponse({
            'success': False,
            'error': 'This feature is only available to users with Agent role'
        }, status=403)
    
    item = get_object_or_404(Item, id=item_id)
    
    try:
        # Get current description
        current_description = item.description or ""
        
        if not current_description.strip():
            return JsonResponse({
                'success': False,
                'error': 'Item has no description to review'
            }, status=400)
        
        # Build RAG context
        rag_context = build_context(
            query=current_description,
            project_id=str(item.project.id),
            limit=10
        )
        
        # Build input text for agent: description + RAG context
        context_text = rag_context.to_context_text() if rag_context.items else "No additional context found."
        
        agent_input = f"""Item Title: {item.title}

Item Description:
{current_description}

---
Context from similar items and related information:
{context_text}
"""
        
        # Execute the issue-analyse-agent
        agent_service = AgentService()
        review = agent_service.execute_agent(
            filename='issue-analyse-agent.yml',
            input_text=agent_input,
            user=request.user,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Convert markdown to HTML for display (create new parser instance to avoid race conditions)
        md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
        review_html = md_parser.convert(review)
        review_html = bleach.clean(review_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.pre_review.generated',
            target=item,
            actor=request.user,
            summary='Pre-Review generated via AI (RAG + issue-analyse-agent)',
        )
        
        return JsonResponse({
            'success': True,
            'review': review,
            'review_html': review_html
        })
        
    except Exception as e:
        # Log activity - error
        activity_service = ActivityService()
        activity_service.log(
            verb='item.pre_review.error',
            target=item,
            actor=request.user,
            summary=f'Pre-Review generation failed: {str(e)}',
        )
        
        logger.error(f"Pre-Review generation failed for item {item_id}: {str(e)}")
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def item_save_pre_review(request, item_id):
    """
    Save Pre-Review as an AI-generated comment on the item.
    
    The comment will be marked with kind=AI_GENERATED and synced to Weaviate.
    
    Only available to users with Agent role.
    """
    import json
    from core.models import CommentKind
    
    # Check user role
    if not request.user.is_authenticated or request.user.role != UserRole.AGENT:
        return JsonResponse({
            'success': False,
            'error': 'This feature is only available to users with Agent role'
        }, status=403)
    
    item = get_object_or_404(Item, id=item_id)
    
    try:
        # Parse request body
        data = json.loads(request.body)
        review = data.get('review', '').strip()
        
        if not review:
            return JsonResponse({
                'success': False,
                'error': 'No review content to save'
            }, status=400)
        
        # Create AI-generated comment
        comment = ItemComment.objects.create(
            item=item,
            author=request.user,
            body=review,
            kind=CommentKind.AI_GENERATED,
            subject='AI Pre-Review'
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.comment.ai_review_saved',
            target=item,
            actor=request.user,
            summary='Pre-Review saved as AI-generated comment',
        )
        
        # The Weaviate sync will happen automatically via signals (if configured)
        
        return JsonResponse({
            'success': True,
            'comment_id': comment.id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Failed to save Pre-Review for item {item_id}: {str(e)}")
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required

@require_POST
def item_change_status(request, item_id):
    """HTMX endpoint to change item status."""
    item = get_object_or_404(Item, id=item_id)
    old_status = item.status
    new_status = request.POST.get('status')
    
    if not new_status:
        return JsonResponse({'success': False, 'error': 'Missing status parameter'}, status=400)
    
    try:
        guard = ItemWorkflowGuard()
        guard.transition(item, new_status, actor=request.user if request.user.is_authenticated else None)
        
        # Check for mail trigger (only if status changed)
        mapping = check_mail_trigger(item)
        if mapping and item.status != old_status:
            # Prepare mail preview for modal
            mail_preview = prepare_mail_preview(item, mapping)
            
            # Return JSON response with mail preview
            return JsonResponse({
                'success': True,
                'item_id': item.id,
                'mail_preview': mail_preview,
                'new_status': item.status,
                'new_status_display': item.get_status_display()
            })
        
        # Return updated status badge (normal HTMX swap)
        response = render(request, 'partials/item_status_badge.html', {'item': item})
        response['HX-Trigger'] = 'statusChanged'
        return response
        
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required

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


@login_required

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


@login_required

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


@login_required

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
        
        # Return success response (for AJAX uploads)
        # If this is an AJAX request (multi-file upload), return simple success
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and not request.headers.get('HX-Request'):
            return HttpResponse("Upload successful", status=200)
        
        # Return updated attachments list for HTMX requests
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


@login_required

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
        
        # Store filename for logging
        filename = attachment.original_name
        
        # Delete the attachment (hard delete: removes file from storage, DB record, and Weaviate via signal)
        storage_service = AttachmentStorageService()
        storage_service.delete_attachment(attachment, hard=True)
        
        # Log activity
        if item:
            activity_service = ActivityService()
            activity_service.log(
                verb='attachment.deleted',
                target=item,
                actor=request.user if request.user.is_authenticated else None,
                summary=f"Deleted file: {filename}",
            )
        
        return JsonResponse({'success': True, 'message': 'Attachment deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def item_view_attachment(request, attachment_id):
    """View an attachment (for viewable file types)."""
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        if attachment.is_deleted:
            return JsonResponse({'success': False, 'error': 'Attachment not found'}, status=404)
        
        # Get file extension using os.path.splitext for reliability
        import os
        _, extension = os.path.splitext(attachment.original_name.lower())
        extension = extension.lstrip('.')  # Remove leading dot
        
        # Read file content
        storage_service = AttachmentStorageService()
        file_content = storage_service.read_attachment(attachment)
        
        # Process based on file type
        if extension == 'md':
            # Render markdown to HTML - create parser instance per request for thread safety
            md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
            html_content = md_parser.convert(file_content.decode('utf-8', errors='replace'))
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
            html_content = file_content.decode('utf-8', errors='replace')
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
            return JsonResponse({'success': True, 'content': file_content.decode('utf-8', errors='replace')})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
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


@login_required
def attachment_view(request, attachment_id):
    """
    Generic attachment view handler.
    This view determines the parent of an attachment and redirects to the appropriate
    item or project attachment view, or serves the attachment directly.
    """
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        if attachment.is_deleted:
            return HttpResponse("Attachment not found", status=404)
        
        # Try to determine parent via AttachmentLink
        first_link = attachment.links.first()
        if first_link:
            # Check the parent type by model name to avoid ContentType lookups
            target = first_link.target
            if target:
                model_name = target.__class__.__name__
                if model_name == 'Item':
                    # Redirect to item detail
                    return redirect('item-detail', item_id=first_link.target_object_id)
                elif model_name == 'Project':
                    # Redirect to project detail
                    return redirect('project-detail', id=first_link.target_object_id)
        
        # If no parent found or parent is not item/project, serve attachment directly
        # Get file extension
        _, extension = os.path.splitext(attachment.original_name.lower())
        extension = extension.lstrip('.')
        
        # Read file content
        storage_service = AttachmentStorageService()
        file_content = storage_service.read_attachment(attachment)
        
        # Determine content type and response
        if extension in ['md', 'txt', 'html', 'htm', 'pdf']:
            # For viewable types, return content for display
            if extension == 'md':
                md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
                html_content = md_parser.convert(file_content.decode('utf-8', errors='replace'))
                clean_html = bleach.clean(
                    html_content,
                    tags=ALLOWED_TAGS,
                    attributes=ALLOWED_ATTRIBUTES,
                    strip=True
                )
                # Return as HTML page
                return HttpResponse(clean_html, content_type='text/html')
            elif extension == 'pdf':
                return HttpResponse(file_content, content_type='application/pdf')
            elif extension in ['html', 'htm']:
                html_content = file_content.decode('utf-8', errors='replace')
                clean_html = bleach.clean(
                    html_content,
                    tags=ALLOWED_TAGS + ['html', 'head', 'body', 'meta', 'title', 'style'],
                    attributes=ALLOWED_ATTRIBUTES,
                    strip=True
                )
                return HttpResponse(clean_html, content_type='text/html')
            else:  # txt
                return HttpResponse(file_content.decode('utf-8', errors='replace'), content_type='text/plain')
        else:
            # For other file types, trigger download
            response = HttpResponse(file_content, content_type=attachment.content_type or 'application/octet-stream')
            response['Content-Disposition'] = f'attachment; filename="{attachment.original_name}"'
            response['Content-Length'] = len(file_content)
            return response
            
    except Http404:
        # Re-raise Http404 to let Django handle it properly
        raise
    except Exception as e:
        logger.error(f"Error viewing attachment {attachment_id}: {str(e)}")
        return HttpResponse(f"Error viewing attachment: {str(e)}", status=500)


@login_required
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


def _get_user_primary_organisation(user):
    """
    Helper function to get the primary organisation of a user.
    
    Args:
        user: User object
        
    Returns:
        Organisation object if user has a primary organisation, None otherwise
    """
    if not user or not user.is_authenticated:
        return None
    
    primary_org = UserOrganisation.objects.filter(
        user=user, 
        is_primary=True
    ).select_related('organisation').first()
    
    return primary_org.organisation if primary_org else None


def _auto_generate_title_from_description(description, user=None):
    """
    Generate a title from description using AI agent if description is provided.
    Returns the generated title or empty string if generation fails or description is empty.
    """
    if not description or not description.strip():
        return ''
    
    try:
        agent_service = AgentService()
        title = agent_service.execute_agent(
            filename='text-to-title-generator.yml',
            input_text=description,
            user=user,
            client_ip=None
        )
        # Clean up the title (remove quotes, newlines, etc.)
        title = title.strip().strip('"').strip("'").replace('\n', ' ').replace('\r', '')
        return title
    except Exception as e:
        logger.error(f"Failed to auto-generate title: {str(e)}")
        return ''


def _update_item_followers(item, follower_ids):
    """
    Update followers for an item.
    
    Args:
        item: Item instance to update followers for
        follower_ids: List of user IDs to set as followers
        
    This function atomically replaces all followers with the provided list.
    Validates that all user IDs are valid and prevents duplicates.
    """
    from core.models import ItemFollower
    
    if not follower_ids:
        follower_ids = []
    
    with transaction.atomic():
        # Remove existing followers
        ItemFollower.objects.filter(item=item).delete()
        
        # Add new followers
        seen_user_ids = set()
        for user_id in follower_ids:
            if not user_id or user_id in seen_user_ids:
                continue
                
            try:
                # Validate user ID is an integer
                user_id_int = int(user_id)
                # Try to get the user
                user = User.objects.filter(id=user_id_int).first()
                if user:
                    ItemFollower.objects.create(item=item, user=user)
                    seen_user_ids.add(user_id)
                else:
                    logger.warning(f"Invalid user ID {user_id} for item {item.id} followers")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid user ID format {user_id} for item {item.id} followers: {e}")


@login_required
def item_create(request):
    """Item create page view."""
    if request.method == 'GET':
        # Show the create form
        projects = Project.objects.all().order_by('name')
        item_types = ItemType.objects.filter(is_active=True).order_by('name')
        organisations = Organisation.objects.all().order_by('name')
        users = User.objects.all().order_by('name')
        statuses = ItemStatus.choices
        
        # Auto-populate default values for requester and organisation
        default_requester = None
        default_organisation = None
        if request.user.is_authenticated:
            default_requester = request.user
            default_organisation = _get_user_primary_organisation(request.user)
        
        # Support pre-selecting project via query parameter
        default_project = None
        project_id = request.GET.get('project')
        nodes = []
        if project_id:
            try:
                # Validate and convert project_id to integer
                project_id_int = int(project_id)
                default_project = Project.objects.get(id=project_id_int)
                # Get nodes for the default project
                nodes = Node.objects.filter(project=default_project).order_by('name')
            except (ValueError, Project.DoesNotExist, TypeError):
                # Invalid or non-existent project ID, ignore it gracefully
                pass
        
        context = {
            'item': None,
            'projects': projects,
            'item_types': item_types,
            'organisations': organisations,
            'users': users,
            'statuses': statuses,
            'default_requester': default_requester,
            'default_organisation': default_organisation,
            'default_project': default_project,
            'nodes': nodes,
        }
        return render(request, 'item_form.html', context)
    
    # Handle POST request (HTMX form submission)
    try:
        project_id = request.POST.get('project')
        project = get_object_or_404(Project, id=project_id)
        
        type_id = request.POST.get('type')
        item_type = get_object_or_404(ItemType, id=type_id)
        
        # Get title and description
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '')
        user_input = request.POST.get('user_input', '')
        
        # Auto-generate title from description if title is empty
        if not title and description:
            title = _auto_generate_title_from_description(description, request.user if request.user.is_authenticated else None)
        
        # Create the item
        item = Item(
            project=project,
            title=title,
            description=description,
            user_input=user_input,
            solution_description=request.POST.get('solution_description', ''),
            type=item_type,
            status=request.POST.get('status', ItemStatus.INBOX),
        )
        
        # Set optional fields with automatic pre-population
        # Auto-populate requester with current user if not explicitly provided
        requester_id = request.POST.get('requester')
        if requester_id:
            item.requester = get_object_or_404(User, id=requester_id)
        elif request.user.is_authenticated:
            # Auto-set requester to current user if not provided
            item.requester = request.user
        
        # Auto-populate organisation with user's primary organisation if not explicitly provided
        org_id = request.POST.get('organisation')
        if org_id:
            item.organisation = get_object_or_404(Organisation, id=org_id)
        elif request.user.is_authenticated:
            item.organisation = _get_user_primary_organisation(request.user)
        
        assigned_to_id = request.POST.get('assigned_to')
        if assigned_to_id:
            item.assigned_to = get_object_or_404(User, id=assigned_to_id)
        
        parent_id = request.POST.get('parent')
        if parent_id:
            item.parent = get_object_or_404(Item, id=parent_id)
        
        solution_release_id = request.POST.get('solution_release')
        if solution_release_id:
            item.solution_release = get_object_or_404(Release, id=solution_release_id)
        
        # Handle node selection and update description before saving
        node_id = request.POST.get('node')
        if node_id:
            node = get_object_or_404(Node, id=node_id, project=item.project)
            # Update description with breadcrumb before saving
            item.update_description_with_breadcrumb(node)
        
        # Save item once with all changes
        item.save()
        
        # Update nodes relationship (ManyToMany, requires item to be saved first)
        if node_id:
            node = get_object_or_404(Node, id=node_id, project=item.project)
            item.nodes.add(node)
            # Validate nodes belong to project
            item.validate_nodes()
        
        # Handle followers (ManyToMany, requires item to be saved first)
        follower_ids = request.POST.getlist('follower_ids')
        _update_item_followers(item, follower_ids)
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.created',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Created item: {item.title}",
        )
        
        # Check for mail trigger
        response_data = {
            'success': True,
            'message': 'Item created successfully',
            'redirect': f'/items/{item.id}/',
            'item_id': item.id,
            'followers': list(item.get_followers().values('id', 'username', 'email', 'name'))
        }
        
        mapping = check_mail_trigger(item)
        if mapping:
            # Prepare mail preview for modal
            mail_preview = prepare_mail_preview(item, mapping)
            response_data['mail_preview'] = mail_preview
        
        return JsonResponse(response_data)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        # Log the full error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Item creation failed: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to create item. Please check your input.'}, status=400)


@login_required
def item_edit(request, item_id):
    """Item edit page view."""
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release', 'parent'
        ).prefetch_related('nodes'),
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
        
        # Get nodes from the current project
        nodes = Node.objects.filter(project=item.project).order_by('name')
        
        context = {
            'item': item,
            'projects': projects,
            'item_types': item_types,
            'organisations': organisations,
            'users': users,
            'statuses': statuses,
            'releases': releases,
            'parent_items': parent_items,
            'nodes': nodes,
        }
        return render(request, 'item_form.html', context)
    
    # Handle POST request (HTMX form submission) - handled by item_update
    return redirect('item-update', item_id=item_id)


@login_required

@require_http_methods(["POST"])
def item_update(request, item_id):
    """Update item details."""
    item = get_object_or_404(Item, id=item_id)
    
    # Capture old status to detect changes
    old_status = item.status
    
    try:
        # Check if node is being updated
        node_id = request.POST.get('node')
        node_changed = node_id is not None
        
        # Get title and description
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', item.description)
        user_input = request.POST.get('user_input', item.user_input)
        
        # Auto-generate title from description if title is empty
        if not title and description:
            title = _auto_generate_title_from_description(description, request.user if request.user.is_authenticated else None)
        
        # Update basic fields
        item.title = title if title else item.title
        # Don't update description from POST if we're changing node - we'll handle it separately
        if not node_changed:
            item.description = description
        else:
            # User might have edited description in form - we need to extract non-breadcrumb content
            # and then re-add the new breadcrumb
            posted_description = description
            # Temporarily set description to extract content without breadcrumb
            item.description = posted_description
        
        item.user_input = user_input
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
        
        # Handle node selection before first save
        if node_changed:
            if node_id:
                node = get_object_or_404(Node, id=node_id, project=item.project)
                # Update description with breadcrumb before saving
                item.update_description_with_breadcrumb(node)
            else:
                # Clear breadcrumb
                item.update_description_with_breadcrumb(None)
        
        # Save item once with all changes
        item.save()
        
        # Update nodes relationship (ManyToMany, requires item to be saved first)
        if node_changed:
            if node_id:
                node = get_object_or_404(Node, id=node_id, project=item.project)
                item.nodes.clear()
                item.nodes.add(node)
                # Validate nodes belong to project
                item.validate_nodes()
            else:
                item.nodes.clear()
        
        # Handle followers (ManyToMany, requires item to be saved first)
        # Only update if follower_ids was provided in the request
        if 'follower_ids' in request.POST:
            follower_ids = request.POST.getlist('follower_ids')
            _update_item_followers(item, follower_ids)
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.updated',
            target=item,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Updated item: {item.title}",
        )
        
        # Check for mail trigger (only if status changed)
        response_data = {
            'success': True,
            'message': 'Item updated successfully',
            'item_id': item.id,
            'redirect': f'/items/{item.id}/',
            'followers': list(item.get_followers().values('id', 'username', 'email', 'name'))
        }
        
        # Only check for mail trigger if status changed
        if item.status != old_status:
            mapping = check_mail_trigger(item)
            if mapping:
                # Prepare mail preview for modal
                mail_preview = prepare_mail_preview(item, mapping)
                response_data['mail_preview'] = mail_preview
        
        return JsonResponse(response_data)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        # Log the full error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Item update failed for item {item_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to update item. Please check your input.'}, status=400)


@login_required

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


@login_required
@require_POST
def item_send_status_mail(request, item_id):
    """Send status change email for an item."""
    from .services.graph.mail_service import send_email
    from .services.mail import get_notification_recipients_for_item
    import bleach
    
    item = get_object_or_404(Item, id=item_id)
    
    # Authorization check: user must be requester, assignee, or have permission to edit item
    # For now, we allow anyone who can view the item (authenticated users)
    # In a more restrictive scenario, check project membership or specific permissions
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        
        # Extract and validate mail data from request
        subject = data.get('subject', '').strip()
        message = data.get('message', '').strip()
        to_address = data.get('to', '').strip()
        from_address = data.get('from_address', '').strip()
        cc_address = data.get('cc_address', '').strip()
        
        if not subject or not message:
            return JsonResponse({'success': False, 'error': 'Subject and message are required'}, status=400)
        
        # Sanitize HTML message to prevent script injection
        # Allow common HTML tags but strip dangerous ones
        allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
                       'ul', 'ol', 'li', 'blockquote', 'a', 'span', 'div', 'table', 'tr', 'td', 'th']
        allowed_attrs = {'a': ['href', 'title'], 'span': ['style'], 'div': ['style']}
        message = bleach.clean(message, tags=allowed_tags, attributes=allowed_attrs, strip=True)
        
        if not to_address:
            # Try to get recipient from requester
            if item.requester and item.requester.email:
                to_address = item.requester.email
            else:
                return JsonResponse({'success': False, 'error': 'No recipient email available'}, status=400)
        
        # Get follower emails for CC using the utility function
        recipients = get_notification_recipients_for_item(item)
        follower_emails = recipients['cc']
        
        # Prepare recipient list
        to = [to_address] if isinstance(to_address, str) else to_address
        
        # Merge follower emails with any existing CC addresses from the request
        cc_list = []
        if cc_address:
            if isinstance(cc_address, str):
                cc_list.append(cc_address)
            else:
                cc_list.extend(cc_address)
        
        # Add follower emails to CC, avoiding duplicates
        seen = set(cc_list)
        for email in follower_emails:
            if email and email not in seen:
                cc_list.append(email)
                seen.add(email)
        
        cc = cc_list if cc_list else None
        
        # Send email using graph service
        result = send_email(
            subject=subject,
            body=message,
            to=to,
            body_is_html=True,
            cc=cc,
            sender=from_address if from_address else None,
            item=item,
            author=request.user if request.user.is_authenticated else None,
            visibility='Internal',
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        if result.success:
            return JsonResponse({
                'success': True,
                'message': 'Email sent successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.error or 'Failed to send email'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f"Failed to send status mail for item {item_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def item_move_project(request, item_id):
    """Move item to a different project with optional email notification."""
    from .services.graph.mail_service import send_email
    from .services.mail import get_notification_recipients_for_item
    from .services.mail.template_processor import process_template
    
    item = get_object_or_404(Item, id=item_id)
    
    try:
        data = json.loads(request.body)
        
        # Extract parameters
        target_project_id = data.get('target_project_id')
        send_mail_to_requester = data.get('send_mail_to_requester', True)
        
        if not target_project_id:
            return JsonResponse({'success': False, 'error': 'Target project is required'}, status=400)
        
        # Get target project
        target_project = get_object_or_404(Project, id=target_project_id)
        
        # Check if the project is actually changing
        if item.project.id == target_project.id:
            return JsonResponse({'success': False, 'error': 'Item is already in the target project'}, status=400)
        
        # Store old project for logging
        old_project = item.project
        
        with transaction.atomic():
            # Update item project
            item.project = target_project
            
            # Clear project-dependent fields that may not be valid in new project
            # Clear nodes (they are project-specific)
            item.nodes.clear()
            
            # Clear parent if it's in a different project
            if item.parent and item.parent.project != target_project:
                item.parent = None
            
            # Clear solution_release if it belongs to different project
            if item.solution_release and item.solution_release.project != target_project:
                item.solution_release = None
            
            # Clear organisation if not a client of the new project
            if item.organisation:
                project_clients = list(target_project.clients.all())
                # Clear organisation if project has clients and organisation is not one of them,
                # or if project has no clients at all
                if not project_clients or item.organisation not in project_clients:
                    item.organisation = None
            
            # Save the item
            item.save()
            
            # Log activity
            activity_service = ActivityService()
            activity_service.log_activity(
                actor=request.user,
                action='item_moved',
                target=item,
                details={
                    'from_project': old_project.name,
                    'to_project': target_project.name,
                },
                client_ip=request.META.get('REMOTE_ADDR')
            )
        
        # Send email notification if requested
        mail_sent = False
        mail_error = None
        
        if send_mail_to_requester:
            try:
                # Get the mail template with key 'moved'
                template = MailTemplate.objects.filter(key='moved', is_active=True).first()
                
                if template and item.requester and item.requester.email:
                    # Reload item with all necessary relations for template processing
                    item = Item.objects.select_related(
                        'project', 'requester', 'assigned_to', 'type', 'solution_release'
                    ).prefetch_related(
                        'requester__user_organisations__organisation'
                    ).get(id=item.id)
                    
                    # Process template with updated item data
                    processed = process_template(template, item)
                    
                    # Get recipients
                    recipients = get_notification_recipients_for_item(item)
                    
                    if recipients['to']:
                        # Send email
                        result = send_email(
                            subject=processed['subject'],
                            body=processed['message'],
                            to=[recipients['to']],
                            body_is_html=True,
                            cc=recipients['cc'] if recipients['cc'] else None,
                            sender=template.from_address if template.from_address else None,
                            item=item,
                            author=request.user,
                            visibility='Internal',
                            client_ip=request.META.get('REMOTE_ADDR')
                        )
                        
                        if result.success:
                            mail_sent = True
                            logger.info(
                                f"Move notification email sent for item {item.id} "
                                f"from project '{old_project.name}' to '{target_project.name}'"
                            )
                        else:
                            mail_error = result.error
                            logger.error(
                                f"Failed to send move notification for item {item.id}: "
                                f"Template: 'moved', Requester: {item.requester.email}, Error: {result.error}"
                            )
                    else:
                        mail_error = "No recipient email available"
                        logger.warning(f"No recipient email for move notification of item {item.id}")
                elif not template:
                    mail_error = "Mail template 'moved' not found or inactive"
                    logger.warning("Mail template with key 'moved' not found or inactive")
                elif not item.requester:
                    mail_error = "Item has no requester"
                elif not item.requester.email:
                    mail_error = "Requester has no email address"
                    
            except Exception as e:
                mail_error = str(e)
                logger.error(
                    f"Exception while sending move notification for item {item.id}: {str(e)}"
                )
        
        # Prepare response
        response_data = {
            'success': True,
            'message': f'Item moved to {target_project.name}',
            'item_id': item.id,
            'new_project_id': target_project.id,
            'new_project_name': target_project.name,
            'mail_sent': mail_sent,
        }
        
        if mail_error:
            response_data['mail_error'] = mail_error
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Http404:
        return JsonResponse({'success': False, 'error': 'Target project not found'}, status=404)
    except ValidationError as e:
        logger.warning(f"Validation error moving item {item_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except IntegrityError as e:
        logger.error(f"Database integrity error moving item {item_id}: {str(e)}")
        return JsonResponse({
            'success': False, 
            'error': 'Failed to move item due to database constraints. Please contact support.'
        }, status=500)
    except Exception as e:
        logger.error(f"Failed to move item {item_id}: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False, 
            'error': 'An unexpected error occurred while moving the item. Please try again or contact support.'
        }, status=500)


@login_required

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


@login_required

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
@login_required

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


@login_required

@require_http_methods(["POST"])
def project_delete(request, id):
    """Delete a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        project.delete()
        return JsonResponse({'success': True, 'redirect': '/projects/'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required

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


@login_required

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


@login_required

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


@login_required

@require_http_methods(["POST"])
def project_add_node(request, id):
    """Add a new node to a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        name = request.POST.get('name')
        node_type = request.POST.get('type')
        description = request.POST.get('description', '')
        parent_node_id = request.POST.get('parent_node_id')
        
        if not name or not node_type:
            return JsonResponse({'success': False, 'error': 'Name and Type are required'}, status=400)
        
        # Handle parent node if specified
        parent_node = None
        if parent_node_id:
            try:
                parent_node = Node.objects.get(id=parent_node_id, project=project)
            except Node.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Invalid parent node'}, status=400)
        
        node = Node.objects.create(
            project=project,
            name=name,
            type=node_type,
            description=description,
            parent_node=parent_node
        )
        
        return JsonResponse({'success': True, 'message': 'Node created successfully', 'node_id': node.id})
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def project_node_detail(request, project_id, node_id):
    """Get details of a specific node as JSON."""
    project = get_object_or_404(Project, id=project_id)
    node = get_object_or_404(Node, id=node_id, project=project)
    
    # Get child nodes
    children = []
    for child in node.child_nodes.all():
        children.append({
            'id': child.id,
            'name': child.name,
            'type': child.type,
            'breadcrumb': child.get_breadcrumb()
        })
    
    data = {
        'id': node.id,
        'name': node.name,
        'type': node.type,
        'description': node.description,
        'parent_node_id': node.parent_node.id if node.parent_node else None,
        'parent_node_name': node.parent_node.name if node.parent_node else None,
        'breadcrumb': node.get_breadcrumb(),
        'children': children
    }
    
    return JsonResponse(data)


@login_required
@require_http_methods(["POST"])
def project_node_update(request, project_id, node_id):
    """Update a node."""
    project = get_object_or_404(Project, id=project_id)
    node = get_object_or_404(Node, id=node_id, project=project)
    
    try:
        name = request.POST.get('name')
        node_type = request.POST.get('type')
        description = request.POST.get('description', '')
        parent_node_id = request.POST.get('parent_node_id')
        
        if not name or not node_type:
            return JsonResponse({'success': False, 'error': 'Name and Type are required'}, status=400)
        
        # Handle parent node if specified
        parent_node = None
        if parent_node_id:
            try:
                parent_node = Node.objects.get(id=parent_node_id, project=project)
                
                # Check for circular references
                if node.would_create_cycle(parent_node):
                    return JsonResponse({
                        'success': False, 
                        'error': 'Cannot set parent: would create circular reference'
                    }, status=400)
                    
            except Node.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Invalid parent node'}, status=400)
        
        # Update node
        node.name = name
        node.type = node_type
        node.description = description
        node.parent_node = parent_node
        node.save()
        
        return JsonResponse({'success': True, 'message': 'Node updated successfully'})
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def project_nodes_tree(request, id):
    """Get the hierarchical tree structure of all nodes in a project."""
    project = get_object_or_404(Project, id=id)
    
    # Get all root nodes with optimized prefetching of children
    root_nodes = Node.objects.filter(
        project=project, 
        parent_node=None
    ).prefetch_related('child_nodes')
    
    # Build the tree using the model method
    tree = [root.get_tree_structure() for root in root_nodes.order_by('name')]
    
    return JsonResponse({'tree': tree})


@login_required

@require_http_methods(["POST"])
def project_add_release(request, id):
    """Add a new release to a project."""
    project = get_object_or_404(Project, id=id)
    
    try:
        name = request.POST.get('name')
        version = request.POST.get('version')
        release_type = request.POST.get('type')
        
        if not name or not version:
            return JsonResponse({'success': False, 'error': 'Name and Version are required'}, status=400)
        
        # Validate release type if provided
        if release_type and release_type not in ReleaseType.values:
            return JsonResponse({'success': False, 'error': f'Invalid release type. Must be one of: {", ".join(ReleaseType.values)}'}, status=400)
        
        release = Release.objects.create(
            project=project,
            name=name,
            version=version,
            type=release_type if release_type else None,
            status=ReleaseStatus.PLANNED
        )
        
        return JsonResponse({'success': True, 'message': 'Release created successfully', 'release_id': release.id})
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def project_attachments_tab(request, id):
    """Return the project attachments tab content."""
    project = get_object_or_404(Project, id=id)
    
    # Get attachments linked to this project
    content_type = ContentType.objects.get_for_model(Project)
    attachment_links = AttachmentLink.objects.filter(
        target_content_type=content_type,
        target_object_id=project.id,
        role=AttachmentRole.PROJECT_FILE
    ).select_related('attachment', 'attachment__created_by').order_by('-created_at')
    
    attachments = [link.attachment for link in attachment_links if not link.attachment.is_deleted]
    
    context = {
        'project': project,
        'attachments': attachments,
    }
    return render(request, 'partials/project_attachments_tab.html', context)


@login_required

@require_POST
def project_upload_attachment(request, id):
    """Upload an attachment to a project."""
    project = get_object_or_404(Project, id=id)
    
    if 'file' not in request.FILES:
        return HttpResponse("No file provided", status=400)
    
    uploaded_file = request.FILES['file']
    
    try:
        # Store attachment
        storage_service = AttachmentStorageService()
        attachment = storage_service.store_attachment(
            file=uploaded_file,
            target=project,
            role=AttachmentRole.PROJECT_FILE,
            created_by=request.user if request.user.is_authenticated else None,
        )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='attachment.uploaded',
            target=project,
            actor=request.user if request.user.is_authenticated else None,
            summary=f"Uploaded file: {attachment.original_name}",
        )
        
        # Return success response (for AJAX uploads)
        # If this is an AJAX request (multi-file upload), return simple success
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and not request.headers.get('HX-Request'):
            return HttpResponse("Upload successful", status=200)
        
        # Return updated attachments list for HTMX requests
        content_type = ContentType.objects.get_for_model(Project)
        attachment_links = AttachmentLink.objects.filter(
            target_content_type=content_type,
            target_object_id=project.id,
            role=AttachmentRole.PROJECT_FILE
        ).select_related('attachment', 'attachment__created_by').order_by('-created_at')
        
        attachments = [link.attachment for link in attachment_links if not link.attachment.is_deleted]
        
        context = {
            'project': project,
            'attachments': attachments,
        }
        response = render(request, 'partials/project_attachments_tab.html', context)
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
        logger.error(f"Attachment upload failed for project {id}: {str(e)}")
        return HttpResponse("Upload failed. Please try again.", status=500)


@login_required

@require_POST
def project_delete_attachment(request, attachment_id):
    """Delete a project attachment."""
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        # Get the project for activity logging
        attachment_link = AttachmentLink.objects.filter(
            attachment=attachment,
            role=AttachmentRole.PROJECT_FILE
        ).first()
        
        if attachment_link and hasattr(attachment_link.target, 'id'):
            project = attachment_link.target
        else:
            project = None
        
        # Store filename for logging
        filename = attachment.original_name
        
        # Delete the attachment (hard delete: removes file from storage, DB record, and Weaviate via signal)
        storage_service = AttachmentStorageService()
        storage_service.delete_attachment(attachment, hard=True)
        
        # Log activity if we have a project
        if project:
            activity_service = ActivityService()
            activity_service.log(
                verb='attachment.deleted',
                target=project,
                actor=request.user if request.user.is_authenticated else None,
                summary=f"Deleted file: {filename}",
            )
        
        return JsonResponse({'success': True, 'message': 'Attachment deleted successfully'})
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Attachment deletion failed: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Failed to delete attachment'}, status=500)


@login_required
def project_view_attachment(request, attachment_id):
    """View a project attachment (for viewable file types)."""
    try:
        attachment = get_object_or_404(Attachment, id=attachment_id)
        
        if attachment.is_deleted:
            return JsonResponse({'success': False, 'error': 'Attachment not found'}, status=404)
        
        # Get file extension using os.path.splitext for reliability
        import os
        _, extension = os.path.splitext(attachment.original_name.lower())
        extension = extension.lstrip('.')  # Remove leading dot
        
        # Read file content
        storage_service = AttachmentStorageService()
        file_content = storage_service.read_attachment(attachment)
        
        # Process based on file type
        if extension == 'md':
            # Render markdown to HTML - create parser instance per request for thread safety
            md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
            html_content = md_parser.convert(file_content.decode('utf-8', errors='replace'))
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
            html_content = file_content.decode('utf-8', errors='replace')
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
            return JsonResponse({'success': True, 'content': file_content.decode('utf-8', errors='replace')})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def project_download_attachment(request, attachment_id):
    """Download a project attachment."""
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


@login_required

@require_POST
def project_import_github_issues(request, id):
    """Import closed GitHub issues for a project."""
    from core.services.github.service import GitHubService
    from core.services.integrations.base import IntegrationDisabled, IntegrationNotConfigured
    
    project = get_object_or_404(Project, id=id)
    
    # Check if project has GitHub repo configured
    if not project.github_owner or not project.github_repo:
        return JsonResponse({
            'success': False,
            'error': 'Project does not have a GitHub repository configured'
        }, status=400)
    
    try:
        # Initialize GitHub service
        github_service = GitHubService()
        
        # Import closed issues
        stats = github_service.import_closed_issues_for_project(
            project=project,
            actor=request.user if request.user.is_authenticated else None,
        )
        
        # Prepare response message
        if stats['issues_imported'] > 0:
            message = (
                f"Successfully imported {stats['issues_imported']} closed issue(s). "
                f"Found {stats['issues_found']} total closed issues. "
                f"Linked {stats['prs_linked']} PR(s)."
            )
        elif stats['issues_found'] > 0:
            message = (
                f"Found {stats['issues_found']} closed issue(s), but all were already imported. "
                f"Linked {stats['prs_linked']} PR(s)."
            )
        else:
            message = "No closed issues found in the repository."
        
        # Add error info if there were errors
        if stats['errors']:
            message += f" Note: {len(stats['errors'])} error(s) occurred during import."
        
        return JsonResponse({
            'success': True,
            'message': message,
            'stats': stats,
        })
    
    except IntegrationDisabled:
        return JsonResponse({
            'success': False,
            'error': 'GitHub integration is not enabled'
        }, status=400)
    
    except IntegrationNotConfigured:
        return JsonResponse({
            'success': False,
            'error': 'GitHub integration is not configured. Please configure GitHub token in admin.'
        }, status=400)
    
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error importing GitHub issues: {e}", exc_info=True)
        
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred while importing issues'
        }, status=500)


# ============================================================================
# Organisation CRUD Views
# ============================================================================

@login_required
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


@login_required
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


@login_required
def organisation_edit(request, id):
    """Organisation edit page view."""
    organisation = get_object_or_404(Organisation, id=id)
    
    if request.method == 'GET':
        # Show the edit form
        context = {
            'organisation': organisation,
        }
        return render(request, 'organisation_form.html', context)


@login_required
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


@login_required
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


@login_required
def organisation_delete(request, id):
    """Delete an organisation."""
    organisation = get_object_or_404(Organisation, id=id)
    
    try:
        organisation.delete()
        return JsonResponse({'success': True, 'redirect': '/organisations/'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required

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


@login_required

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


@login_required

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


@login_required

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


@login_required

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

@login_required
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


@login_required
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


@login_required
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


@login_required

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


@login_required

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

@login_required
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


@login_required

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


@login_required

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


@login_required

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


@login_required

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


@login_required

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


@login_required

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

@login_required
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


@login_required
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


@login_required
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


@login_required

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


@login_required

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


@login_required

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


@login_required

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

@login_required
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

@login_required
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


@login_required
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


@login_required

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

@login_required
def change_detail(request, id):
    """Change detail page view."""
    change = get_object_or_404(
        Change.objects.select_related(
            'project', 'created_by', 'release'
        ).prefetch_related('approvals__approver', 'organisations'),
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
    
    # Get users for approver selection - filter by organisations assigned to change
    # Only show users with role != USER who are members of the change's organisations
    change_org_ids = list(change.organisations.values_list('id', flat=True))
    if change_org_ids:
        # Get users who belong to any of the change's organisations and have role != USER
        all_users = User.objects.filter(
            active=True,
            user_organisations__organisation_id__in=change_org_ids
        ).exclude(
            user_organisations__role=UserRole.USER
        ).distinct().order_by('name')
    else:
        # If no organisations assigned, show all active users with role != USER
        all_users = User.objects.filter(active=True).exclude(
            user_organisations__role=UserRole.USER
        ).distinct().order_by('name')
    
    # Load attachments for each approval
    approval_ct = ContentType.objects.get_for_model(ChangeApproval)
    for approval in change.approvals.all():
        approval.attachments = AttachmentLink.objects.filter(
            target_content_type=approval_ct,
            target_object_id=approval.id,
            role=AttachmentRole.APPROVER_ATTACHMENT
        ).select_related('attachment')
    
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


@login_required
def change_create(request):
    """Change create page view."""
    if request.method == 'GET':
        # Show the create form
        projects = Project.objects.all().order_by('name')
        statuses = ChangeStatus.choices
        risk_levels = RiskLevel.choices
        releases = Release.objects.all().select_related('project').order_by('-update_date')
        organisations = Organisation.objects.all().order_by('name')
        
        context = {
            'change': None,
            'projects': projects,
            'statuses': statuses,
            'risk_levels': risk_levels,
            'releases': releases,
            'organisations': organisations,
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
                organisations = Organisation.objects.all().order_by('name')
                context = {
                    'change': None,
                    'projects': projects,
                    'statuses': statuses,
                    'risk_levels': risk_levels,
                    'releases': releases,
                    'organisations': organisations,
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
        
        # Get safety relevant flag
        is_safety_relevant = request.POST.get('is_safety_relevant') == 'true'
        
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
            is_safety_relevant=is_safety_relevant,
            created_by=request.user if request.user.is_authenticated else None,
        )
        
        # Set organisations (many-to-many field, must be set after object creation)
        organisation_ids = request.POST.getlist('organisations')
        if organisation_ids:
            change.organisations.set(organisation_ids)
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.created',
            target=change,
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
            organisations = Organisation.objects.all().order_by('name')
            context = {
                'change': None,
                'projects': projects,
                'statuses': statuses,
                'risk_levels': risk_levels,
                'releases': releases,
                'organisations': organisations,
                'error': str(e)
            }
            return render(request, 'change_form.html', context)


@login_required
def change_edit(request, id):
    """Change edit page view."""
    change = get_object_or_404(Change, id=id)
    
    if request.method == 'GET':
        # Show the edit form
        projects = Project.objects.all().order_by('name')
        statuses = ChangeStatus.choices
        risk_levels = RiskLevel.choices
        releases = Release.objects.filter(project=change.project).order_by('-update_date')
        organisations = Organisation.objects.all().order_by('name')
        
        context = {
            'change': change,
            'projects': projects,
            'statuses': statuses,
            'risk_levels': risk_levels,
            'releases': releases,
            'organisations': organisations,
        }
        return render(request, 'change_form.html', context)


@login_required

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
        
        # Update safety flag
        change.is_safety_relevant = request.POST.get('is_safety_relevant') == 'true'
        
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
        
        # Update organisations (many-to-many field)
        organisation_ids = request.POST.getlist('organisations')
        if organisation_ids:
            change.organisations.set(organisation_ids)
        else:
            change.organisations.clear()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.updated',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Change "{change.title}" was updated'
        )
        
        return JsonResponse({'success': True, 'message': 'Change updated successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required

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


@login_required

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
        activity_service = ActivityService()
        activity_service.log(
            verb='change.approver_added',
            target=change,
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


@login_required

@require_http_methods(["POST"])
def change_remove_approver(request, id, approval_id):
    """Remove an approver from a change."""
    change = get_object_or_404(Change, id=id)
    approval = get_object_or_404(ChangeApproval, id=approval_id, change=change)
    
    try:
        approver_name = approval.approver.name
        approval.delete()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.approver_removed',
            target=change,
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


@login_required

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
        activity_service = ActivityService()
        activity_service.log(
            verb='change.approved',
            target=change,
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


@login_required

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
        activity_service = ActivityService()
        activity_service.log(
            verb='change.rejected',
            target=change,
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


@login_required
@require_http_methods(["POST"])
def change_update_approver(request, id, approval_id):
    """Update approver details including new fields and attachment."""
    from core.services.storage.service import StorageService
    
    change = get_object_or_404(Change, id=id)
    approval = get_object_or_404(ChangeApproval, id=approval_id, change=change)
    
    # Maximum file size: 10MB
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    try:
        # Update informed_at
        informed_at = request.POST.get('informed_at')
        if informed_at:
            approval.informed_at = informed_at
        else:
            approval.informed_at = None
        
        # Update approved flag
        approval.approved = request.POST.get('approved') == 'true'
        
        # Update approved_at
        approved_at = request.POST.get('approved_at')
        if approved_at:
            approval.approved_at = approved_at
        else:
            approval.approved_at = None
        
        # Update notes and comment
        approval.notes = request.POST.get('notes', '')
        approval.comment = request.POST.get('comment', '')
        
        # Update status based on approved flag
        if approval.approved:
            approval.status = ApprovalStatus.APPROVED
            if not approval.decision_at:
                approval.decision_at = approval.approved_at or timezone.now()
        
        approval.save()
        
        # Handle file upload if present
        if 'attachment' in request.FILES:
            file = request.FILES['attachment']
            
            # Validate file size
            if file.size > MAX_FILE_SIZE:
                return JsonResponse({
                    'success': False, 
                    'error': f'File size exceeds maximum allowed size of {MAX_FILE_SIZE // (1024*1024)}MB'
                }, status=400)
            
            # Validate file type
            allowed_extensions = ['.pdf', '.png', '.jpg', '.jpeg', '.txt', '.eml', '.msg']
            file_ext = file.name.lower()[file.name.rfind('.'):] if '.' in file.name else ''
            if file_ext not in allowed_extensions:
                return JsonResponse({
                    'success': False,
                    'error': f'File type not allowed. Allowed types: {", ".join(allowed_extensions)}'
                }, status=400)
            
            # Use storage service to save file
            storage_service = StorageService()
            attachment = storage_service.save_file(
                file=file,
                user=request.user,
                original_name=file.name
            )
            
            # Create attachment link
            approval_ct = ContentType.objects.get_for_model(ChangeApproval)
            
            AttachmentLink.objects.create(
                attachment=attachment,
                target_content_type=approval_ct,
                target_object_id=approval.id,
                role=AttachmentRole.APPROVER_ATTACHMENT
            )
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.approver_updated',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Approver {approval.approver.name} details updated'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Approver updated successfully',
            'reload': True
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def change_remove_approver_attachment(request, id, approval_id, attachment_id):
    """Remove an attachment from an approver."""
    change = get_object_or_404(Change, id=id)
    approval = get_object_or_404(ChangeApproval, id=approval_id, change=change)
    attachment = get_object_or_404(Attachment, id=attachment_id)
    
    try:
        # Find and remove the attachment link
        approval_ct = ContentType.objects.get_for_model(ChangeApproval)
        
        link = AttachmentLink.objects.filter(
            attachment=attachment,
            target_content_type=approval_ct,
            target_object_id=approval.id,
            role=AttachmentRole.APPROVER_ATTACHMENT
        ).first()
        
        if link:
            link.delete()
            # Mark attachment as deleted (soft delete)
            attachment.is_deleted = True
            attachment.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.approver_attachment_removed',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Attachment removed from approver {approval.approver.name}'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Attachment removed successfully',
            'reload': True
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def change_polish_risk_description(request, id):
    """Polish the risk description using AI agent."""
    change = get_object_or_404(Change, id=id)
    
    try:
        # Get current risk description
        risk_description = change.risk_description or ''
        
        if not risk_description.strip():
            return JsonResponse({
                'success': False, 
                'error': 'Risk description is empty. Please add some text first.'
            }, status=400)
        
        # Execute the change-text-polish-agent
        agent_service = AgentService()
        polished_text = agent_service.execute_agent(
            filename='change-text-polish-agent.yml',
            input_text=risk_description,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Update the risk description
        change.risk_description = polished_text
        change.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.ai_risk_polished',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'AI polished risk description for change "{change.title}"'
        )
        
        return JsonResponse({
            'success': True,
            'text': polished_text,
            'message': 'Risk description improved successfully'
        })
    except Exception as e:
        logger.error(f"Error polishing risk description: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def change_optimize_mitigation(request, id):
    """Optimize the mitigation plan using AI agent."""
    change = get_object_or_404(Change, id=id)
    
    try:
        # Get current mitigation plan
        mitigation = change.mitigation or ''
        
        if not mitigation.strip():
            return JsonResponse({
                'success': False, 
                'error': 'Mitigation plan is empty. Please add some text first.'
            }, status=400)
        
        # Execute the text-optimization-agent
        agent_service = AgentService()
        optimized_text = agent_service.execute_agent(
            filename='text-optimization-agent.yml',
            input_text=mitigation,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Update the mitigation plan
        change.mitigation = optimized_text
        change.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.ai_mitigation_optimized',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'AI optimized mitigation plan for change "{change.title}"'
        )
        
        return JsonResponse({
            'success': True,
            'text': optimized_text,
            'message': 'Mitigation plan optimized successfully'
        })
    except Exception as e:
        logger.error(f"Error optimizing mitigation plan: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def change_optimize_rollback(request, id):
    """Optimize the rollback plan using AI agent."""
    change = get_object_or_404(Change, id=id)
    
    try:
        # Get current rollback plan
        rollback_plan = change.rollback_plan or ''
        
        if not rollback_plan.strip():
            return JsonResponse({
                'success': False, 
                'error': 'Rollback plan is empty. Please add some text first.'
            }, status=400)
        
        # Execute the text-optimization-agent
        agent_service = AgentService()
        optimized_text = agent_service.execute_agent(
            filename='text-optimization-agent.yml',
            input_text=rollback_plan,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Update the rollback plan
        change.rollback_plan = optimized_text
        change.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.ai_rollback_optimized',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'AI optimized rollback plan for change "{change.title}"'
        )
        
        return JsonResponse({
            'success': True,
            'text': optimized_text,
            'message': 'Rollback plan optimized successfully'
        })
    except Exception as e:
        logger.error(f"Error optimizing rollback plan: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def change_assess_risk(request, id):
    """Assess risk level automatically using AI agent."""
    change = get_object_or_404(Change, id=id)
    
    try:
        # Combine all relevant fields for risk assessment
        risk_description = change.risk_description or ''
        mitigation = change.mitigation or ''
        rollback_plan = change.rollback_plan or ''
        
        # Build input for the agent
        agent_input = f"""Risk Description:
{risk_description}

Mitigation Plan:
{mitigation}

Rollback Plan:
{rollback_plan}"""
        
        if not risk_description.strip() and not mitigation.strip() and not rollback_plan.strip():
            return JsonResponse({
                'success': False, 
                'error': 'At least one of Risk Description, Mitigation Plan, or Rollback Plan must have content.'
            }, status=400)
        
        # Execute the change-risk-assessment-agent
        agent_service = AgentService()
        assessment_result = agent_service.execute_agent(
            filename='change-risk-assessment-agent.yml',
            input_text=agent_input,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Parse the result to extract risk level and reason
        # Expected format can be JSON with RiskClass and RiskClassReason fields
        risk_class = RiskLevel.NORMAL  # Default to NORMAL if no risk class can be determined
        risk_reason = None  # Will be set based on parsing
        
        # Try to parse as JSON first
        try:
            # Attempt to parse JSON response
            result_json = json.loads(assessment_result)
            
            # Extract RiskClassReason for the description
            # ONLY use RiskClassReason if present, otherwise use full JSON
            risk_reason = result_json.get('RiskClassReason', assessment_result)
            
            # Extract and normalize RiskClass for the enum
            if 'RiskClass' in result_json and result_json['RiskClass']:
                risk_class_value = result_json['RiskClass'].lower().strip()
                
                # Normalize to RiskLevel enum values
                if risk_class_value in ['very high', 'veryhigh', 'sehr hoch']:
                    risk_class = RiskLevel.VERY_HIGH
                elif risk_class_value in ['low', 'niedrig', 'gering']:
                    risk_class = RiskLevel.LOW
                elif risk_class_value in ['high', 'hoch']:
                    risk_class = RiskLevel.HIGH
                elif risk_class_value in ['normal', 'mittel']:
                    risk_class = RiskLevel.NORMAL
                # If unrecognized value, keep default NORMAL (set above)
        except (json.JSONDecodeError, AttributeError):
            # If not JSON, assessment_result is None, or .lower() fails on None,
            # fall back to text parsing
            risk_reason = assessment_result  # Use full text for non-JSON responses
            assessment_lower = assessment_result.lower() if assessment_result else ''
            if 'very high' in assessment_lower or 'veryhigh' in assessment_lower or 'sehr hoch' in assessment_lower:
                risk_class = RiskLevel.VERY_HIGH
            elif 'low' in assessment_lower or 'niedrig' in assessment_lower or 'gering' in assessment_lower:
                risk_class = RiskLevel.LOW
            elif 'high' in assessment_lower or 'hoch' in assessment_lower:
                # This check is after "very high" to avoid false matches
                risk_class = RiskLevel.HIGH
            # If no match, keep default NORMAL (set above)
        
        # Update risk level
        old_risk = change.risk
        change.risk = risk_class
        
        # Update or append the reasoning to risk description
        # Check if an AI assessment section already exists and replace it
        risk_desc = change.risk_description or ''
        ai_marker = '## AI Risk Assessment'
        
        if ai_marker in risk_desc:
            # Find and replace existing AI assessment
            parts = risk_desc.split(ai_marker)
            # Keep everything before the marker, append new assessment
            change.risk_description = f"{parts[0].rstrip()}\n\n{ai_marker}\n{risk_reason}"
        elif risk_desc:
            # Append new assessment to existing description
            change.risk_description = f"{risk_desc}\n\n{ai_marker}\n{risk_reason}"
        else:
            # No existing description, just add the assessment
            change.risk_description = f"{ai_marker}\n{risk_reason}"
        
        change.save()
        
        # Log activity
        activity_service = ActivityService()
        activity_service.log(
            verb='change.ai_risk_assessed',
            target=change,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'AI assessed risk level for change "{change.title}" from {old_risk} to {risk_class}'
        )
        
        return JsonResponse({
            'success': True,
            'risk_class': risk_class,
            'risk_class_display': change.get_risk_display(),
            'risk_reason': risk_reason,
            'message': f'Risk level set to {change.get_risk_display()}'
        })
    except Exception as e:
        logger.error(f"Error assessing risk: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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


@login_required
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


@login_required
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


@login_required
def search(request):
    """
    Global search view using Weaviate hybrid search.
    
    Query parameters:
    - q: Search query (required, minimum 2 characters)
    - mode: Search mode ('hybrid', 'similar', 'keyword'; default: 'hybrid')
    - type: Optional filter by object type (e.g., 'item', 'project', 'comment')
    - project_id: Optional filter by project ID
    """
    from django.conf import settings
    from core.services.weaviate.service import global_search
    
    query = request.GET.get('q', '').strip()
    search_mode = request.GET.get('mode', 'hybrid').strip()
    object_type = request.GET.get('type', '').strip()
    project_id = request.GET.get('project_id', '').strip()
    
    # Validate search mode
    valid_modes = ['hybrid', 'similar', 'keyword']
    if search_mode not in valid_modes:
        search_mode = 'hybrid'
    
    # Get configuration from settings
    min_query_length = getattr(settings, 'WEAVIATE_SEARCH_MIN_QUERY_LENGTH', 2)
    search_limit = getattr(settings, 'WEAVIATE_SEARCH_LIMIT', 25)
    search_alpha = getattr(settings, 'WEAVIATE_SEARCH_ALPHA', 0.5)
    
    # Initialize context
    context = {
        'query': query,
        'search_mode': search_mode,
        'object_type': object_type,
        'project_id': project_id,
        'results': [],
        'error': None,
        'min_query_length': min_query_length,
    }
    
    # Only search if query is provided and meets minimum length
    if query:
        if len(query) < min_query_length:
            context['error'] = f'Bitte mindestens {min_query_length} Zeichen eingeben.'
        else:
            try:
                # Build filters
                filters = {}
                if object_type:
                    filters['type'] = object_type
                if project_id:
                    filters['project_id'] = project_id
                
                # Execute search with mode
                results = global_search(
                    query=query,
                    limit=search_limit,
                    alpha=search_alpha,
                    filters=filters if filters else None,
                    mode=search_mode,
                )
                
                context['results'] = results
                
            except Exception as e:
                # Log error without including user query for security
                logger.exception("Search error occurred")
                context['error'] = 'Suchfehler: Weaviate ist möglicherweise nicht verfügbar. Bitte versuchen Sie es später erneut.'
    
    return render(request, 'search.html', context)


# ===========================
# Mail Template Views
# ===========================

@login_required
def mail_templates(request):
    """Mail templates list view with search and filter."""
    templates = MailTemplate.objects.all()
    
    # Search by key or subject
    search_query = request.GET.get('q', '').strip()
    if search_query:
        templates = templates.filter(
            Q(key__icontains=search_query) | Q(subject__icontains=search_query)
        )
    
    # Filter by is_active
    is_active_filter = request.GET.get('is_active', '').strip()
    if is_active_filter == 'true':
        templates = templates.filter(is_active=True)
    elif is_active_filter == 'false':
        templates = templates.filter(is_active=False)
    
    context = {
        'templates': templates,
        'search_query': search_query,
        'is_active_filter': is_active_filter,
    }
    return render(request, 'mail_templates.html', context)


@login_required
def mail_template_detail(request, id):
    """Mail template detail view."""
    template = get_object_or_404(MailTemplate, id=id)
    
    context = {
        'template': template,
    }
    return render(request, 'mail_template_detail.html', context)


@login_required
def mail_template_create(request):
    """Show create form for new mail template."""
    context = {
        'template': None,
    }
    return render(request, 'mail_template_form.html', context)


@login_required
def mail_template_edit(request, id):
    """Show edit form for existing mail template."""
    template = get_object_or_404(MailTemplate, id=id)
    
    context = {
        'template': template,
    }
    return render(request, 'mail_template_form.html', context)


@login_required
@require_http_methods(["POST"])
def mail_template_update(request, id):
    """Create or update a mail template."""
    try:
        # Parse form data
        key = request.POST.get('key', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        from_name = request.POST.get('from_name', '').strip()
        from_address = request.POST.get('from_address', '').strip()
        cc_address = request.POST.get('cc_address', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        action = request.POST.get('action', 'save')
        
        # Validate required fields
        if not key:
            return JsonResponse({'success': False, 'error': 'Key is required'}, status=400)
        if not subject:
            return JsonResponse({'success': False, 'error': 'Subject is required'}, status=400)
        if not message:
            return JsonResponse({'success': False, 'error': 'Message is required'}, status=400)
        
        # Validate key format (lowercase, numbers, hyphens only)
        if not re.match(r'^[a-z0-9\-]+$', key):
            return JsonResponse({
                'success': False, 
                'error': 'Key must contain only lowercase letters, numbers, and hyphens'
            }, status=400)
        
        # Create or update
        if id == 0:
            # Create new template
            # Check if key already exists
            if MailTemplate.objects.filter(key=key).exists():
                return JsonResponse({
                    'success': False, 
                    'error': f'A template with key "{key}" already exists'
                }, status=400)
            
            template = MailTemplate.objects.create(
                key=key,
                subject=subject,
                message=message,
                from_name=from_name,
                from_address=from_address,
                cc_address=cc_address,
                is_active=is_active
            )
            
            # Log activity
            activity_service = ActivityService()
            activity_service.log(
                verb='mail_template.created',
                target=template,
                actor=request.user if request.user.is_authenticated else None,
                summary=f'Created mail template "{template.key}"'
            )
            
            message_text = f'Mail template "{key}" created successfully'
        else:
            # Update existing template
            template = get_object_or_404(MailTemplate, id=id)
            
            # Update fields
            template.subject = subject
            template.message = message
            template.from_name = from_name
            template.from_address = from_address
            template.cc_address = cc_address
            template.is_active = is_active
            template.save()
            
            # Log activity
            activity_service = ActivityService()
            activity_service.log(
                verb='mail_template.updated',
                target=template,
                actor=request.user if request.user.is_authenticated else None,
                summary=f'Updated mail template "{template.key}"'
            )
            
            message_text = f'Mail template "{template.key}" updated successfully'
        
        # Determine redirect based on action
        if action == 'save_close':
            redirect_url = reverse('mail-templates')
        else:
            redirect_url = reverse('mail-template-detail', args=[template.id])
        
        return JsonResponse({
            'success': True,
            'message': message_text,
            'redirect': redirect_url,
            'template_id': template.id
        })
        
    except Exception as e:
        logger.error(f"Error saving mail template: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def mail_template_delete(request, id):
    """Delete a mail template."""
    # get_object_or_404 will raise Http404 if not found, which Django will handle
    template = get_object_or_404(MailTemplate, id=id)
    template_key = template.key
    
    try:
        # Log activity before deletion
        activity_service = ActivityService()
        activity_service.log(
            verb='mail_template.deleted',
            target=template,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Deleted mail template "{template_key}"'
        )
        
        template.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Mail template "{template_key}" deleted successfully',
            'redirect': reverse('mail-templates')
        })
        
    except Exception as e:
        logger.error(f"Error deleting mail template: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def mail_template_generate_ai(request, id):
    """Generate subject and message using AI agent."""
    try:
        # Parse JSON body
        data = json.loads(request.body)
        context = data.get('context', '').strip()
        
        if not context:
            return JsonResponse({
                'success': False, 
                'error': 'Context description is required'
            }, status=400)
        
        # Execute the create-mail-template agent
        agent_service = AgentService()
        result = agent_service.execute_agent(
            filename='create-mail-template.yml',
            input_text=context,
            user=request.user if request.user.is_authenticated else None,
            client_ip=request.META.get('REMOTE_ADDR')
        )
        
        # Parse JSON response from agent
        try:
            # Clean up potential markdown code blocks
            result = result.strip()
            if result.startswith('```json'):
                result = result[7:]
            if result.startswith('```'):
                result = result[3:]
            if result.endswith('```'):
                result = result[:-3]
            result = result.strip()
            
            result_json = json.loads(result)
            
            # Extract Subject and Message
            subject = result_json.get('Subject', '')
            message = result_json.get('Message', '')
            
            if not subject or not message:
                return JsonResponse({
                    'success': False, 
                    'error': 'AI agent did not return valid Subject and Message fields'
                }, status=500)
            
            # Log activity if template exists
            if id > 0:
                template = get_object_or_404(MailTemplate, id=id)
                activity_service = ActivityService()
                activity_service.log(
                    verb='mail_template.ai_generated',
                    target=template,
                    actor=request.user if request.user.is_authenticated else None,
                    summary=f'AI generated content for mail template "{template.key}"'
                )
            
            return JsonResponse({
                'success': True,
                'subject': subject,
                'message': message
            })
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI agent response as JSON: {result}")
            return JsonResponse({
                'success': False, 
                'error': f'AI agent returned invalid JSON: {str(e)}'
            }, status=500)
        
    except Exception as e:
        logger.error(f"Error generating mail template with AI: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# Mail Action Mapping Views

@login_required
def mail_action_mappings(request):
    """Mail action mappings list view with search and filter."""
    mappings = MailActionMapping.objects.select_related('item_type', 'mail_template').all()
    
    # Search by status or type name
    search_query = request.GET.get('q', '').strip()
    if search_query:
        mappings = mappings.filter(
            Q(item_status__icontains=search_query) | 
            Q(item_type__name__icontains=search_query) |
            Q(item_type__key__icontains=search_query) |
            Q(mail_template__key__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        mappings = mappings.filter(item_status=status_filter)
    
    # Filter by type
    type_filter = request.GET.get('type', '').strip()
    if type_filter:
        try:
            type_id = int(type_filter)
            mappings = mappings.filter(item_type_id=type_id)
        except ValueError:
            pass
    
    # Filter by is_active
    is_active_filter = request.GET.get('is_active', '').strip()
    if is_active_filter == 'true':
        mappings = mappings.filter(is_active=True)
    elif is_active_filter == 'false':
        mappings = mappings.filter(is_active=False)
    
    # Apply consistent ordering
    mappings = mappings.order_by('item_status', 'item_type__name')
    
    # Get all item types and statuses for filters
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    item_statuses = ItemStatus.choices
    
    context = {
        'mappings': mappings,
        'search_query': search_query,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'is_active_filter': is_active_filter,
        'item_types': item_types,
        'item_statuses': item_statuses,
    }
    return render(request, 'mail_action_mappings.html', context)


@login_required
def mail_action_mapping_detail(request, id):
    """Mail action mapping detail view."""
    mapping = get_object_or_404(MailActionMapping.objects.select_related('item_type', 'mail_template'), id=id)
    
    context = {
        'mapping': mapping,
    }
    return render(request, 'mail_action_mapping_detail.html', context)


@login_required
def mail_action_mapping_create(request):
    """Show create form for new mail action mapping."""
    # Get all active item types and mail templates
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    mail_templates = MailTemplate.objects.filter(is_active=True).order_by('key')
    item_statuses = ItemStatus.choices
    
    context = {
        'mapping': None,
        'item_types': item_types,
        'mail_templates': mail_templates,
        'item_statuses': item_statuses,
    }
    return render(request, 'mail_action_mapping_form.html', context)


@login_required
def mail_action_mapping_edit(request, id):
    """Show edit form for existing mail action mapping."""
    mapping = get_object_or_404(MailActionMapping.objects.select_related('item_type', 'mail_template'), id=id)
    
    # Get all active item types and mail templates
    item_types = ItemType.objects.filter(is_active=True).order_by('name')
    mail_templates = MailTemplate.objects.filter(is_active=True).order_by('key')
    item_statuses = ItemStatus.choices
    
    context = {
        'mapping': mapping,
        'item_types': item_types,
        'mail_templates': mail_templates,
        'item_statuses': item_statuses,
    }
    return render(request, 'mail_action_mapping_form.html', context)


@login_required
@require_http_methods(["POST"])
def mail_action_mapping_update(request, id):
    """Create or update a mail action mapping with uniqueness validation."""
    try:
        # Parse form data
        item_status = request.POST.get('item_status', '').strip()
        item_type_id = request.POST.get('item_type', '').strip()
        mail_template_id = request.POST.get('mail_template', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        action = request.POST.get('action', 'save')
        
        # Validate required fields
        if not item_status:
            return JsonResponse({'success': False, 'error': 'Status ist erforderlich'}, status=400)
        if not item_type_id:
            return JsonResponse({'success': False, 'error': 'Typ ist erforderlich'}, status=400)
        if not mail_template_id:
            return JsonResponse({'success': False, 'error': 'Mail-Template ist erforderlich'}, status=400)
        
        # Validate item_status is valid choice
        valid_statuses = [choice[0] for choice in ItemStatus.choices]
        if item_status not in valid_statuses:
            return JsonResponse({'success': False, 'error': 'Ungültiger Status'}, status=400)
        
        # Get related objects
        try:
            item_type = ItemType.objects.get(id=int(item_type_id))
        except (ItemType.DoesNotExist, ValueError):
            return JsonResponse({'success': False, 'error': 'Ungültiger Typ'}, status=400)
        
        try:
            mail_template = MailTemplate.objects.get(id=int(mail_template_id))
        except (MailTemplate.DoesNotExist, ValueError):
            return JsonResponse({'success': False, 'error': 'Ungültiges Mail-Template'}, status=400)
        
        # Check for uniqueness (status + type combination)
        existing_mapping = MailActionMapping.objects.filter(
            item_status=item_status,
            item_type=item_type
        )
        
        # If editing, exclude the current mapping from uniqueness check
        if id != 0:
            existing_mapping = existing_mapping.exclude(id=id)
        
        if existing_mapping.exists():
            status_display = dict(ItemStatus.choices).get(item_status, item_status)
            return JsonResponse({
                'success': False,
                'error': f'Ein Mapping für Status "{status_display}" und Typ "{item_type.name}" existiert bereits.'
            }, status=400)
        
        # Create or update
        if id == 0:
            # Create new mapping
            mapping = MailActionMapping.objects.create(
                item_status=item_status,
                item_type=item_type,
                mail_template=mail_template,
                is_active=is_active
            )
            
            # Log activity
            activity_service = ActivityService()
            activity_service.log(
                verb='mail_action_mapping.created',
                target=mapping,
                actor=request.user if request.user.is_authenticated else None,
                summary=f'Created mail action mapping: {mapping}'
            )
            
            message_text = f'Mail action mapping created successfully'
        else:
            # Update existing mapping
            mapping = get_object_or_404(MailActionMapping, id=id)
            
            # Update fields
            mapping.item_status = item_status
            mapping.item_type = item_type
            mapping.mail_template = mail_template
            mapping.is_active = is_active
            mapping.save()
            
            # Log activity
            activity_service = ActivityService()
            activity_service.log(
                verb='mail_action_mapping.updated',
                target=mapping,
                actor=request.user if request.user.is_authenticated else None,
                summary=f'Updated mail action mapping: {mapping}'
            )
            
            message_text = f'Mail action mapping updated successfully'
        
        # Determine redirect based on action
        if action == 'save_close':
            redirect_url = reverse('mail-action-mappings')
        else:
            redirect_url = reverse('mail-action-mapping-detail', args=[mapping.id])
        
        return JsonResponse({
            'success': True,
            'message': message_text,
            'redirect': redirect_url,
            'mapping_id': mapping.id
        })
        
    except Exception as e:
        logger.error(f"Error saving mail action mapping: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def mail_action_mapping_delete(request, id):
    """Delete a mail action mapping."""
    mapping = get_object_or_404(MailActionMapping, id=id)
    mapping_str = str(mapping)
    
    try:
        # Log activity before deletion
        activity_service = ActivityService()
        activity_service.log(
            verb='mail_action_mapping.deleted',
            target=mapping,
            actor=request.user if request.user.is_authenticated else None,
            summary=f'Deleted mail action mapping: {mapping_str}'
        )
        
        mapping.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Mail action mapping deleted successfully',
            'redirect': reverse('mail-action-mappings')
        })
        
    except Exception as e:
        logger.error(f"Error deleting mail action mapping: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# Email Reply/Forward Views
@login_required
def email_prepare_reply(request, comment_id):
    """Prepare reply data for an email comment."""
    from core.services.mail.email_reply_service import prepare_reply
    
    try:
        comment = get_object_or_404(ItemComment, id=comment_id)
        
        # Only allow reply for email comments
        if comment.kind not in ['EmailIn', 'EmailOut']:
            return JsonResponse({'success': False, 'error': 'Can only reply to email comments'}, status=400)
        
        # Prepare reply data
        reply_data = prepare_reply(comment, current_user=request.user)
        
        return JsonResponse({
            'success': True,
            'data': reply_data,
        })
    except Exception as e:
        logger.error(f"Error preparing reply: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def email_prepare_reply_all(request, comment_id):
    """Prepare reply-all data for an email comment."""
    from core.services.mail.email_reply_service import prepare_reply_all
    
    try:
        comment = get_object_or_404(ItemComment, id=comment_id)
        
        # Only allow reply for email comments
        if comment.kind not in ['EmailIn', 'EmailOut']:
            return JsonResponse({'success': False, 'error': 'Can only reply to email comments'}, status=400)
        
        # Prepare reply-all data
        reply_data = prepare_reply_all(comment, current_user=request.user)
        
        return JsonResponse({
            'success': True,
            'data': reply_data,
        })
    except Exception as e:
        logger.error(f"Error preparing reply all: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def email_prepare_forward(request, comment_id):
    """Prepare forward data for an email comment."""
    from core.services.mail.email_reply_service import prepare_forward
    
    try:
        comment = get_object_or_404(ItemComment, id=comment_id)
        
        # Only allow forward for email comments
        if comment.kind not in ['EmailIn', 'EmailOut']:
            return JsonResponse({'success': False, 'error': 'Can only forward email comments'}, status=400)
        
        # Prepare forward data
        forward_data = prepare_forward(comment, current_user=request.user)
        
        return JsonResponse({
            'success': True,
            'data': forward_data,
        })
    except Exception as e:
        logger.error(f"Error preparing forward: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def email_send_reply(request):
    """Send a reply/forward email from the compose modal."""
    from core.services.graph.mail_service import send_email
    import json
    
    try:
        data = json.loads(request.body)
        
        item_id = data.get('item_id')
        to_addresses = data.get('to', [])
        cc_addresses = data.get('cc', [])
        subject = data.get('subject', '')
        body = data.get('body', '')
        in_reply_to = data.get('in_reply_to', '')
        
        # Validate inputs
        if not item_id:
            return JsonResponse({'success': False, 'error': 'Item ID is required'}, status=400)
        
        if not to_addresses or not isinstance(to_addresses, list):
            return JsonResponse({'success': False, 'error': 'At least one recipient is required'}, status=400)
        
        if not subject:
            return JsonResponse({'success': False, 'error': 'Subject is required'}, status=400)
        
        # Get item
        item = get_object_or_404(Item, id=item_id)
        
        # Send email
        result = send_email(
            subject=subject,
            body=body,
            to=to_addresses,
            cc=cc_addresses if cc_addresses else None,
            body_is_html=True,
            item=item,
            author=request.user,
            visibility='Internal',
        )
        
        if result.success:
            # Log activity
            activity_service = ActivityService()
            activity_service.log(
                verb='email.sent',
                target=item,
                actor=request.user,
                summary=f"Sent email: {subject}",
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Email sent successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.error or 'Failed to send email'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
