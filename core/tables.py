"""
Django tables for Item model.
"""
import django_tables2 as tables
from django.utils.html import format_html
from django.urls import reverse
from .models import Item


class ItemTable(tables.Table):
    """
    Table for displaying Item list with sortable columns.
    """
    
    # Updated at column
    updated_at = tables.DateTimeColumn(
        verbose_name='Updated',
        format='Y-m-d H:i',
        attrs={
            'td': {'class': 'text-muted small'},
        }
    )
    
    # Title column with link to detail view
    title = tables.Column(
        verbose_name='Title',
        orderable=True,
        attrs={'td': {'class': 'item-title-cell'}}
    )
    
    # Type column
    type = tables.Column(
        verbose_name='Type',
        orderable=True,
        accessor='type.name'
    )
    
    # Project column
    project = tables.Column(
        verbose_name='Project',
        orderable=True,
        accessor='project.name',
        attrs={'td': {'class': 'small'}}
    )
    
    # Organisation column
    organisation = tables.Column(
        verbose_name='Organisation',
        orderable=True,
        accessor='organisation.name',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    # Requester column
    requester = tables.Column(
        verbose_name='Requester',
        orderable=True,
        accessor='requester.username',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    # Assigned to column
    assigned_to = tables.Column(
        verbose_name='Assigned To',
        orderable=True,
        accessor='assigned_to.username',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('updated_at', 'title', 'type', 'project', 'organisation', 'requester', 'assigned_to')
        attrs = {
            'class': 'table table-hover',
            'thead': {'class': 'table-light'}
        }
        order_by = '-updated_at'
    
    def render_title(self, record):
        """
        Render title column with link to detail view and truncated description.
        """
        url = reverse('item-detail', kwargs={'item_id': record.id})
        title_html = format_html(
            '<a href="{}" class="text-decoration-none"><strong>{}</strong></a>',
            url,
            record.title
        )
        
        if record.description:
            # Truncate description to 15 words
            words = record.description.split()
            truncated = ' '.join(words[:15])
            if len(words) > 15:
                truncated += '...'
            desc_html = format_html(
                '<br><small class="text-muted">{}</small>',
                truncated
            )
            return format_html('{}{}', title_html, desc_html)
        
        return title_html
    
    def render_type(self, record):
        """
        Render type column as a badge.
        """
        return format_html(
            '<span class="badge bg-secondary">{}</span>',
            record.type.name
        )
    
    def render_organisation(self, value, record):
        """
        Render organisation column with em dash for empty values.
        """
        if record.organisation:
            return record.organisation.name
        return format_html('<span class="text-muted">—</span>')
    
    def render_requester(self, value, record):
        """
        Render requester column with em dash for empty values.
        """
        if record.requester:
            return record.requester.username
        return format_html('<span class="text-muted">—</span>')
    
    def render_assigned_to(self, value, record):
        """
        Render assigned_to column with em dash for empty values.
        """
        if record.assigned_to:
            return record.assigned_to.username
        return format_html('<span class="text-muted">—</span>')
