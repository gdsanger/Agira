"""
Django filters for Item model.
"""
import django_filters
from django import forms
from .models import Item, Project, ItemType, Organisation, User


class ItemFilter(django_filters.FilterSet):
    """
    FilterSet for Item model.
    Supports filtering by search query, project, type, organisation, requester, and assigned_to.
    """
    # Search filter (title or description)
    q = django_filters.CharFilter(
        method='filter_search',
        label='Search',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by title or description...'
        })
    )
    
    # Project filter
    project = django_filters.ModelChoiceFilter(
        queryset=Project.objects.all().order_by('name'),
        label='Project',
        empty_label='All Projects',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Type filter
    type = django_filters.ModelChoiceFilter(
        queryset=ItemType.objects.all().order_by('name'),
        label='Type',
        empty_label='All Types',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Organisation filter
    organisation = django_filters.ModelChoiceFilter(
        queryset=Organisation.objects.all().order_by('name'),
        label='Organisation',
        empty_label='All Organisations',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Requester filter
    requester = django_filters.ModelChoiceFilter(
        queryset=User.objects.filter(active=True).order_by('username'),
        label='Requester',
        empty_label='All Requesters',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Assigned to filter
    assigned_to = django_filters.ModelChoiceFilter(
        queryset=User.objects.filter(active=True).order_by('username'),
        label='Assigned To',
        empty_label='All Assignees',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = Item
        fields = ['q', 'project', 'type', 'organisation', 'requester', 'assigned_to']
    
    def filter_search(self, queryset, name, value):
        """
        Filter items by search query in title or description.
        """
        if value:
            from django.db.models import Q
            return queryset.filter(
                Q(title__icontains=value) | Q(description__icontains=value)
            )
        return queryset


class RelatedItemsFilter(django_filters.FilterSet):
    """
    FilterSet for related (child) items.
    Supports filtering by search query, type, status, and assigned_to.
    """
    # Search filter (title or description)
    q = django_filters.CharFilter(
        method='filter_search',
        label='Search',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by title or description...'
        })
    )
    
    # Type filter
    type = django_filters.ModelChoiceFilter(
        queryset=ItemType.objects.all().order_by('name'),
        label='Type',
        empty_label='All Types',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Status filter
    status = django_filters.ChoiceFilter(
        choices=Item._meta.get_field('status').choices,
        label='Status',
        empty_label='All Statuses',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Assigned to filter
    assigned_to = django_filters.ModelChoiceFilter(
        queryset=User.objects.filter(active=True).order_by('username'),
        label='Assigned To',
        empty_label='All Assignees',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = Item
        fields = ['q', 'type', 'status', 'assigned_to']
    
    def filter_search(self, queryset, name, value):
        """
        Filter items by search query in title or description.
        """
        if value:
            from django.db.models import Q
            return queryset.filter(
                Q(title__icontains=value) | Q(description__icontains=value)
            )
        return queryset


class EmbedItemFilter(django_filters.FilterSet):
    """
    FilterSet for Item model in embed portal.
    Supports filtering by status, type, and search query.
    IMPORTANT: Always excludes items where intern=True for security.
    """
    # Search filter (title or description)
    q = django_filters.CharFilter(
        method='filter_search',
        label='Search',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search in title...'
        })
    )
    
    # Status filter with custom choices for embed
    status = django_filters.ChoiceFilter(
        choices=[
            ('', 'All Statuses'),
            ('closed', 'Closed'),
            ('not_closed', 'Not Closed'),
        ],
        method='filter_status',
        label='Status',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    # Type filter
    type = django_filters.ModelChoiceFilter(
        queryset=ItemType.objects.filter(is_active=True).order_by('name'),
        label='Type',
        empty_label='All Types',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = Item
        fields = ['q', 'status', 'type']
    
    def filter_search(self, queryset, name, value):
        """
        Filter items by search query in title or description.
        """
        if value:
            from django.db.models import Q
            return queryset.filter(
                Q(title__icontains=value) | Q(description__icontains=value)
            )
        return queryset
    
    def filter_status(self, queryset, name, value):
        """
        Filter items by status.
        Supports 'closed' and 'not_closed' as special values.
        """
        from .models import ItemStatus
        if value == 'closed':
            return queryset.filter(status=ItemStatus.CLOSED)
        elif value == 'not_closed':
            return queryset.exclude(status=ItemStatus.CLOSED)
        return queryset
    
    @property
    def qs(self):
        """
        Override queryset to always exclude intern items for security.
        This is fail-safe - no matter what filters are applied, intern items are excluded.
        """
        parent_qs = super().qs
        return parent_qs.filter(intern=False)
