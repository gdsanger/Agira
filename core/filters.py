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
