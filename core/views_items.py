"""
Class-based views for Item list views using django-tables2 and django-filter.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django_tables2 import SingleTableMixin
from django_tables2.config import RequestConfig
from django_filters.views import FilterView
from django.conf import settings

from .models import Item, ItemStatus, Project, ItemType, Organisation, User, Release
from .tables import ItemTable
from .filters import ItemFilter, KanbanFilter


class StatusItemListView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """
    Base class for status-based Item list views.
    
    Combines django-tables2 (SingleTableMixin) and django-filter (FilterView)
    to provide filtering, sorting, and pagination for Items.
    
    The status scope is fixed and cannot be removed via UI filters.
    Pipeline order: Status-Scope → Filter → Table
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
        Get the base queryset filtered by status.
        
        This enforces the status scope before any other filters are applied.
        The status scope cannot be removed via UI filters.
        """
        if self.item_status is None:
            raise NotImplementedError("Subclasses must set item_status")
        
        # Base queryset with status scope (fixed, not UI-removable)
        queryset = Item.objects.filter(status=self.item_status).select_related(
            'project', 'type', 'organisation', 'requester', 'assigned_to'
        )
        
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
        filterset = self.filterset_class(self.request.GET, queryset=filtered_qs)
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


class ItemsReadyView(StatusItemListView):
    """Items Ready for Release - items ready to be released."""
    item_status = ItemStatus.READY_FOR_RELEASE
    page_title = "Items - Ready for Release"
    page_description = "Items ready to be released"


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
        Get all non-closed items with related data.
        """
        queryset = Item.objects.exclude(status=ItemStatus.CLOSED).select_related(
            'project', 'type', 'organisation', 'requester', 'assigned_to', 'solution_release'
        ).prefetch_related('external_mappings')
        
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
    
    # Determine which view class to use based on the status
    view_class_map = {
        ItemStatus.INBOX: ItemsInboxView,
        ItemStatus.BACKLOG: ItemsBacklogView,
        ItemStatus.WORKING: ItemsWorkingView,
        ItemStatus.TESTING: ItemsTestingView,
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
    filterset = filterset_class(request.GET, queryset=queryset)
    
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
