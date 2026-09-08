"""
Class-based views for Item list views using django-tables2 and django-filter.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.views.generic import ListView
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.db.models import Count
from django_tables2 import SingleTableMixin
from django_tables2.config import RequestConfig
from django_filters.views import FilterView
from django.conf import settings

from .models import Item, ItemStatus, Project, ItemType, Organisation, User, Release
from .tables import ItemTable
from .filters import ItemFilter, KanbanFilter
from .services.workflow import ItemWorkflowGuard
from .visibility import scope_items


class StatusItemListView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """
    Base class for status-based Item list views.
    
    Combines django-tables2 (SingleTableMixin) and django-filter (FilterView)
    to provide filtering, sorting, and pagination for Items.
    
    The status scope is fixed and cannot be removed via UI filters.
    Pipeline order: Visibility-Scope → Status-Scope → Filter → Table
    """
    model = Item
    table_class = ItemTable
    filterset_class = ItemFilter
    template_name = 'items_list.html'
    context_object_name = 'items'
    paginate_by = getattr(settings, 'ITEMS_PER_PAGE', 25)
    
    # Subclasses must set this to the specific ItemStatus
    item_status = None
    
    # Page title and description for subclasses to override
    page_title = "Items"
    page_description = ""
    
    def get_queryset(self):
        """
        Get the base queryset filtered by visibility and status.

        This enforces the status scope before any other filters are applied.
        The status scope cannot be removed via UI filters.
        """
        if self.item_status is None:
            raise NotImplementedError("Subclasses must set item_status")

        # Base queryset with status scope (fixed, not UI-removable)
        # comment_count is annotated here (single aggregate query) so the table
        # can display it without triggering a per-row query.
        # The visibility scope (#1248) sits outermost: search, filters, sorting
        # and pagination all run on the user's own slice of the data.
        queryset = scope_items(
            Item.objects.filter(status=self.item_status), self.request.user
        ).select_related(
            'project', 'type', 'organisation', 'requester', 'assigned_to'
        ).annotate(comment_count=Count('comments'))

        return queryset
    
    def get_context_data(self, **kwargs):
        """
        Add additional context for the template.
        """
        context = super().get_context_data(**kwargs)
        
        # Add page title and description
        context['page_title'] = self.page_title
        context['page_description'] = self.page_description
        
        # Add distinct values for header filters
        context['distinct_values'] = self.get_distinct_values()
        
        return context
    
    def get_distinct_values(self):
        """
        Get distinct values for header-based filters.
        
        Returns distinct values from the status-scoped + currently filtered queryset.
        This ensures that the distinct values are relevant to the current view.
        
        Performance: Limited to 100 distinct values per field to prevent unbounded queries.
        """
        # Get the filtered queryset (after status scope and user filters)
        filtered_qs = self.get_queryset()
        
        # Apply user filters if any
        filterset = self.filterset_class(
            self.request.GET, queryset=filtered_qs, request=self.request
        )
        if filterset.is_valid():
            filtered_qs = filterset.qs
        
        distinct_values = {}
        
        # Project distinct values
        projects = Project.objects.filter(
            id__in=filtered_qs.values_list('project_id', flat=True).distinct()[:100]
        ).order_by('name')
        distinct_values['project'] = list(projects)
        
        # Type distinct values
        types = ItemType.objects.filter(
            id__in=filtered_qs.values_list('type_id', flat=True).distinct()[:100]
        ).order_by('name')
        distinct_values['type'] = list(types)
        
        # Organisation distinct values
        org_ids = filtered_qs.exclude(organisation__isnull=True).values_list(
            'organisation_id', flat=True
        ).distinct()[:100]
        organisations = Organisation.objects.filter(id__in=org_ids).order_by('name')
        distinct_values['organisation'] = list(organisations)
        
        # Requester distinct values
        requester_ids = filtered_qs.exclude(requester__isnull=True).values_list(
            'requester_id', flat=True
        ).distinct()[:100]
        requesters = User.objects.filter(id__in=requester_ids).order_by('username')
        distinct_values['requester'] = list(requesters)
        
        # Assigned to distinct values
        assigned_ids = filtered_qs.exclude(assigned_to__isnull=True).values_list(
            'assigned_to_id', flat=True
        ).distinct()[:100]
        assigned_users = User.objects.filter(id__in=assigned_ids).order_by('username')
        distinct_values['assigned_to'] = list(assigned_users)
        
        return distinct_values


class ItemsInboxView(StatusItemListView):
    """Items Inbox - new items that need to be triaged."""
    item_status = ItemStatus.INBOX
    page_title = "Items - Inbox"
    page_description = "New items that need to be triaged"


class ItemsBacklogView(StatusItemListView):
    """Items Backlog - planned items for future work."""
    item_status = ItemStatus.BACKLOG
    page_title = "Items - Backlog"
    page_description = "Planned items for future work"


class ItemsWorkingView(StatusItemListView):
    """Items Working - items currently in progress."""
    item_status = ItemStatus.WORKING
    page_title = "Items - Working"
    page_description = "Items currently in progress"


class ItemsTestingView(StatusItemListView):
    """Items Testing - items being tested."""
    item_status = ItemStatus.TESTING
    page_title = "Items - Testing"
    page_description = "Items being tested"


class ItemsReviewView(StatusItemListView):
    """Items Review - items marked for coordination or open questions."""
    item_status = ItemStatus.REVIEW
    page_title = "Items - Review"
    page_description = "Items marked for review/coordination"


class ItemsReadyView(StatusItemListView):
    """Items Ready for Release - items ready to be released."""
    item_status = ItemStatus.READY_FOR_RELEASE
    page_title = "Items - Ready for Release"
    page_description = "Items ready to be released"


class UserScopedItemListView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """
    Base class for user-scoped Item list views (assigned_to, responsible).

    Similar to StatusItemListView but filters by user relationship instead of status.
    Shows items across all statuses (except closed) for the current user.
    Pipeline order: Visibility-Scope → User-Scope → Filter → Table
    """
    model = Item
    table_class = ItemTable
    filterset_class = ItemFilter
    template_name = 'items_list.html'
    context_object_name = 'items'
    paginate_by = getattr(settings, 'ITEMS_PER_PAGE', 25)

    # Subclasses must set this to the field name ('assigned_to' or 'responsible')
    user_field = None

    # Page title and description for subclasses to override
    page_title = "Items"
    page_description = ""

    def get_queryset(self):
        """
        Get the base queryset filtered by user relationship.

        This enforces the user scope before any other filters are applied.
        The user scope cannot be removed via UI filters.
        """
        if self.user_field is None:
            raise NotImplementedError("Subclasses must set user_field")

        # Base queryset with user scope (fixed, not UI-removable)
        # Exclude closed items by default.
        # The visibility scope (#1248) applies here too: item visibility is
        # derived from the project, so an item in a project that is not assigned
        # to the user stays hidden even when the user is its assignee.
        filter_kwargs = {
            self.user_field: self.request.user,
        }
        queryset = scope_items(
            Item.objects.filter(**filter_kwargs), self.request.user
        ).exclude(
            status=ItemStatus.CLOSED
        ).select_related(
            'project', 'type', 'organisation', 'requester', 'assigned_to'
        ).annotate(comment_count=Count('comments'))

        return queryset

    def get_context_data(self, **kwargs):
        """
        Add additional context for the template.
        """
        context = super().get_context_data(**kwargs)

        # Add page title and description
        context['page_title'] = self.page_title
        context['page_description'] = self.page_description

        # Add distinct values for header filters
        context['distinct_values'] = self.get_distinct_values()

        return context

    def get_distinct_values(self):
        """
        Get distinct values for header-based filters.

        Returns distinct values from the user-scoped + currently filtered queryset.
        This ensures that the distinct values are relevant to the current view.

        Performance: Limited to 100 distinct values per field to prevent unbounded queries.
        """
        # Get the filtered queryset (after user scope and user filters)
        filtered_qs = self.get_queryset()

        # Apply user filters if any
        filterset = self.filterset_class(
            self.request.GET, queryset=filtered_qs, request=self.request
        )
        if filterset.is_valid():
            filtered_qs = filterset.qs

        distinct_values = {}

        # Project distinct values
        projects = Project.objects.filter(
            id__in=filtered_qs.values_list('project_id', flat=True).distinct()[:100]
        ).order_by('name')
        distinct_values['project'] = list(projects)

        # Type distinct values
        types = ItemType.objects.filter(
            id__in=filtered_qs.values_list('type_id', flat=True).distinct()[:100]
        ).order_by('name')
        distinct_values['type'] = list(types)

        # Organisation distinct values
        org_ids = filtered_qs.exclude(organisation__isnull=True).values_list(
            'organisation_id', flat=True
        ).distinct()[:100]
        organisations = Organisation.objects.filter(id__in=org_ids).order_by('name')
        distinct_values['organisation'] = list(organisations)

        # Requester distinct values
        requester_ids = filtered_qs.exclude(requester__isnull=True).values_list(
            'requester_id', flat=True
        ).distinct()[:100]
        requesters = User.objects.filter(id__in=requester_ids).order_by('username')
        distinct_values['requester'] = list(requesters)

        # Assigned to distinct values
        assigned_ids = filtered_qs.exclude(assigned_to__isnull=True).values_list(
            'assigned_to_id', flat=True
        ).distinct()[:100]
        assigned_users = User.objects.filter(id__in=assigned_ids).order_by('username')
        distinct_values['assigned_to'] = list(assigned_users)

        return distinct_values


class ItemsAssignedToMeView(UserScopedItemListView):
    """Items Assigned to Me - items assigned to the current user."""
    user_field = 'assigned_to'
    page_title = "Items - Assigned to Me"
    page_description = "Items assigned to you"


class ItemsResponsibleForView(UserScopedItemListView):
    """Items I'm Responsible For - items where current user is responsible."""
    user_field = 'responsible'
    page_title = "Items - Responsible For"
    page_description = "Items you are responsible for"


class ItemsKanbanView(LoginRequiredMixin, FilterView):
    """
    Kanban board view for all non-closed items.
    Shows items organized by status columns with drag-and-drop support.
    """
    model = Item
    filterset_class = KanbanFilter
    template_name = 'items_kanban.html'
    context_object_name = 'items'
    
    def get_queryset(self):
        """
        Get all non-closed items the current user can see, with related data.
        """
        queryset = scope_items(
            Item.objects.all(), self.request.user
        ).exclude(status=ItemStatus.CLOSED).select_related(
            'project', 'type', 'organisation', 'requester', 'assigned_to', 'solution_release'
        ).prefetch_related('external_mappings').annotate(comment_count=Count('comments'))

        return queryset
    
    def get_context_data(self, **kwargs):
        """
        Add items grouped by status and other context data.
        """
        context = super().get_context_data(**kwargs)
        
        # Get filtered items
        filtered_items = context['object_list']
        
        # Define status order for Kanban columns
        status_order = [
            ItemStatus.INBOX,
            ItemStatus.BACKLOG,
            ItemStatus.WORKING,
            ItemStatus.TESTING,
            ItemStatus.REVIEW,
            ItemStatus.READY_FOR_RELEASE,
        ]
        
        # Group items by status
        items_by_status = {}
        for status in status_order:
            items_by_status[status] = [
                item for item in filtered_items if item.status == status
            ]
        
        context['items_by_status'] = items_by_status
        context['status_order'] = status_order
        context['page_title'] = 'Kanban Board'
        context['page_description'] = 'All non-closed items organized by status'
        
        return context


@login_required
@require_POST
def item_list_status_update(request, item_id):
    """Change an item's status straight from a list view — without any mail flow (#1249).

    Deliberately a separate endpoint from ``item_change_status``: that one is the
    DetailView path and, after the transition, evaluates ``check_mail_trigger`` and
    hands a mail preview back so the detail page can open its mail confirmation
    modal. A list row has nowhere to show that modal and no way to let the user
    confirm or cancel the mail, so a list-driven change must never enter that flow.

    This endpoint therefore does exactly one thing: run the existing
    ``ItemWorkflowGuard`` transition (status-choice validation + activity log, the
    same validation the detail path uses) and swap the re-rendered status cell back
    in. Permissions match the detail path: authenticated users, no item-level rules.

    Returns the ``partials/item_status_cell.html`` fragment - 200 on success, 400
    with an error message on a rejected status. In both cases the fragment is
    rendered from the *persisted* status, so a rejected change snaps the select back
    to what is actually stored instead of leaving the user's pick on screen.
    """
    item = get_object_or_404(Item, id=item_id)
    new_status = (request.POST.get('status') or '').strip()

    error = None
    if not new_status:
        error = 'Kein Status übermittelt.'
    else:
        try:
            ItemWorkflowGuard().transition(item, new_status, actor=request.user)
        except ValidationError as exc:
            error = ' '.join(exc.messages)

    if error:
        # Drop whatever the rejected attempt may have left on the instance.
        item.refresh_from_db()

    return render(
        request,
        'partials/item_status_cell.html',
        {
            'item': item,
            'status_choices': ItemStatus.choices,
            'status_error': error,
            'status_saved': error is None,
        },
        status=400 if error else 200,
    )


@login_required
def item_list_delete(request, item_id):
    """
    Delete an item from a list view and return the refreshed list HTML.

    This endpoint is called via HTMX from the list view delete button.
    After deletion, it re-renders the complete list container with updated data.
    """
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    # Get the item and its status before deletion
    item = get_object_or_404(Item, id=item_id)
    item_status = item.status

    # Delete the item
    item.delete()

    # Check the HTTP Referer to determine which view to re-render
    # This allows us to support both status-based and user-scoped views
    referer = request.META.get('HTTP_REFERER', '')
    view_class = None

    # Check for user-scoped views first
    if '/items/assigned/' in referer:
        view_class = ItemsAssignedToMeView
    elif '/items/responsible/' in referer:
        view_class = ItemsResponsibleForView
    else:
        # Fallback to status-based views
        view_class_map = {
            ItemStatus.INBOX: ItemsInboxView,
            ItemStatus.BACKLOG: ItemsBacklogView,
            ItemStatus.WORKING: ItemsWorkingView,
            ItemStatus.TESTING: ItemsTestingView,
            ItemStatus.REVIEW: ItemsReviewView,
            ItemStatus.READY_FOR_RELEASE: ItemsReadyView,
        }
        view_class = view_class_map.get(item_status)

    if not view_class:
        # Fallback: render empty container
        return HttpResponse(
            '<div id="items-list-container"><div class="alert alert-success">Item deleted successfully</div></div>',
            content_type='text/html'
        )
    
    # Instantiate the view properly with setup
    view_instance = view_class()
    view_instance.request = request
    view_instance.args = ()
    view_instance.kwargs = {}
    view_instance.setup(request)
    
    # Get queryset and apply filters
    queryset = view_instance.get_queryset()
    filterset_class = view_instance.filterset_class
    filterset = filterset_class(request.GET, queryset=queryset, request=request)
    
    # Create table instance
    table_class = view_instance.table_class
    table = table_class(filterset.qs if filterset.is_valid() else queryset)
    
    # Configure pagination
    RequestConfig(request, paginate={'per_page': view_instance.paginate_by}).configure(table)
    
    # Build context
    context = {
        'table': table,
        'filter': filterset,
        'request': request,
    }
    
    # Render the partial template
    return render(request, 'partials/items_list_container.html', context)
