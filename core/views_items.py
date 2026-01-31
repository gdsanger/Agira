"""
Class-based views for Item list views using django-tables2 and django-filter.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django_tables2 import SingleTableMixin
from django_filters.views import FilterView
from django.conf import settings

from .models import Item, ItemStatus, Project, ItemType, Organisation, User
from .tables import ItemTable
from .filters import ItemFilter


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


class ItemsPlanningView(StatusItemListView):
    """Items Planning - items in planning phase.
    
    Note: Uses ItemStatus.PLANING (not PLANNING) to match model definition.
    """
    item_status = ItemStatus.PLANING
    page_title = "Items - Planning"
    page_description = "Items in planning phase"


class ItemsSpecificationView(StatusItemListView):
    """Items Specification - items in specification phase."""
    item_status = ItemStatus.SPECIFICATION
    page_title = "Items - Specification"
    page_description = "Items in specification phase"
