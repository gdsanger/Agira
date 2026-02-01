"""
Django tables for Item model.
"""
import django_tables2 as tables
from django.utils.html import format_html
from django.urls import reverse
from .models import Item, Release


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
        accessor='type__name'
    )
    
    # Project column
    project = tables.Column(
        verbose_name='Project',
        orderable=True,
        accessor='project__name',
        attrs={'td': {'class': 'small'}}
    )
    
    # Organisation column
    organisation = tables.Column(
        verbose_name='Organisation',
        orderable=True,
        accessor='organisation__name',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    # Requester column
    requester = tables.Column(
        verbose_name='Requester',
        orderable=True,
        accessor='requester__username',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    # Assigned to column
    assigned_to = tables.Column(
        verbose_name='Assigned To',
        orderable=True,
        accessor='assigned_to__username',
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
        return format_html('<span class="text-muted">{}</span>', '—')
    
    def render_requester(self, value, record):
        """
        Render requester column with em dash for empty values.
        """
        if record.requester:
            return record.requester.username
        return format_html('<span class="text-muted">{}</span>', '—')
    
    def render_assigned_to(self, value, record):
        """
        Render assigned_to column with em dash for empty values.
        """
        if record.assigned_to:
            return record.assigned_to.username
        return format_html('<span class="text-muted">{}</span>', '—')


class RelatedItemsTable(tables.Table):
    """
    Table for displaying related (child) items.
    Shows items that have a relation from the parent item with type='Related'.
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
        accessor='type__name'
    )
    
    # Status column
    status = tables.Column(
        verbose_name='Status',
        orderable=True
    )
    
    # Assigned to column
    assigned_to = tables.Column(
        verbose_name='Assigned To',
        orderable=True,
        accessor='assigned_to__username',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('updated_at', 'title', 'type', 'status', 'assigned_to')
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
    
    def render_status(self, value):
        """
        Render status column as a badge with emoji.
        """
        from .models import ItemStatus
        status_dict = dict(ItemStatus.choices)
        display_text = status_dict.get(value, value)
        
        # Color mapping for status badges
        status_colors = {
            'Inbox': 'bg-info',
            'Backlog': 'bg-secondary',
            'Working': 'bg-warning',
            'Testing': 'bg-primary',
            'ReadyForRelease': 'bg-success',
            'Planing': 'bg-info',
            'Specification': 'bg-info',
            'Closed': 'bg-dark',
        }
        color = status_colors.get(value, 'bg-secondary')
        
        return format_html(
            '<span class="badge {}">{}</span>',
            color,
            display_text
        )
    
    def render_assigned_to(self, value, record):
        """
        Render assigned_to column with em dash for empty values.
        """
        if record.assigned_to:
            return record.assigned_to.username
        return format_html('<span class="text-muted">{}</span>', '—')


class EmbedItemTable(tables.Table):
    """
    Table for displaying items in the embed portal.
    Includes columns for ID, Title, Type, Status, Updated, Solution Release, and Solution indicator.
    """
    
    # ID column
    id = tables.Column(
        verbose_name='ID',
        orderable=True,
        attrs={'td': {'class': 'text-muted small'}}
    )
    
    # Title column with link to embed detail view
    title = tables.Column(
        verbose_name='Title',
        orderable=True,
        attrs={'td': {'class': 'item-title-cell'}}
    )
    
    # Type column
    type = tables.Column(
        verbose_name='Type',
        orderable=True,
        accessor='type__name'
    )
    
    # Status column
    status = tables.Column(
        verbose_name='Status',
        orderable=True
    )
    
    # Updated at column
    updated_at = tables.DateTimeColumn(
        verbose_name='Updated',
        format='d.m.Y H:i',
        orderable=True,
        attrs={'td': {'class': 'text-muted small'}}
    )
    
    # Solution Release column
    solution_release = tables.Column(
        verbose_name='Solution Release',
        orderable=True,
        accessor='solution_release__version',
        empty_values=()
    )
    
    # Solution indicator column
    solution = tables.Column(
        verbose_name='Solution',
        orderable=False,
        empty_values=(),
        attrs={'td': {'class': 'text-center', 'style': 'width: 80px;'}}
    )
    
    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('id', 'title', 'type', 'status', 'updated_at', 'solution_release', 'solution')
        attrs = {
            'class': 'table table-hover',
            'thead': {'class': 'table-dark'}
        }
        order_by = '-updated_at'
    
    def render_title(self, record, value):
        """
        Render title column with link to embed detail view.
        Token is passed via table.token attribute.
        """
        token = getattr(self, 'token', '')
        url = reverse('embed-issue-detail', kwargs={'issue_id': record.id}) + f'?token={token}'
        return format_html(
            '<a href="{}" class="text-decoration-none">{}</a>',
            url,
            value
        )
    
    def render_type(self, record):
        """
        Render type column as a badge.
        """
        return format_html(
            '<span class="badge bg-secondary">{}</span>',
            record.type.name
        )
    
    def render_status(self, value):
        """
        Render status column as a badge with emoji.
        """
        from .models import ItemStatus
        status_dict = dict(ItemStatus.choices)
        display_text = status_dict.get(value, value)
        
        # Color mapping for status badges
        status_colors = {
            'Inbox': 'bg-info',
            'Backlog': 'bg-secondary',
            'Working': 'bg-warning',
            'Testing': 'bg-primary',
            'ReadyForRelease': 'bg-success',
            'Planing': 'bg-info',
            'Specification': 'bg-info',
            'Closed': 'bg-dark',
        }
        color = status_colors.get(value, 'bg-secondary')
        
        return format_html(
            '<span class="badge {}">{}</span>',
            color,
            display_text
        )
    
    def render_solution_release(self, value, record):
        """
        Render solution_release column with em dash for empty values.
        """
        if record.solution_release:
            return record.solution_release.version
        return format_html('<span class="text-muted">{}</span>', '—')
    
    def render_solution(self, record):
        """
        Render solution indicator button if solution exists.
        """
        if record.solution_description and record.solution_description.strip():
            return format_html(
                '<button type="button" class="btn btn-sm btn-outline-info" '
                'data-bs-toggle="modal" '
                'data-bs-target="#solutionModal{}" '
                'title="View Solution Description" '
                'aria-label="View solution description for issue {}">'
                '<i class="bi bi-lightbulb"></i>'
                '</button>',
                record.id,
                record.id
            )
        return ''


class ReleaseItemsTable(tables.Table):
    """
    Table for displaying items associated with a specific release.
    Similar to ItemTable but excludes the release column.
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
        accessor='type__name'
    )
    
    # Status column
    status = tables.Column(
        verbose_name='Status',
        orderable=True
    )
    
    # Organisation column
    organisation = tables.Column(
        verbose_name='Organisation',
        orderable=True,
        accessor='organisation__name',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    # Assigned to column
    assigned_to = tables.Column(
        verbose_name='Assigned To',
        orderable=True,
        accessor='assigned_to__username',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('updated_at', 'title', 'type', 'status', 'organisation', 'assigned_to')
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
    
    def render_status(self, value):
        """
        Render status column as a badge with emoji.
        """
        from .models import ItemStatus
        status_dict = dict(ItemStatus.choices)
        display_text = status_dict.get(value, value)
        
        # Color mapping for status badges
        status_colors = {
            'Inbox': 'bg-info',
            'Backlog': 'bg-secondary',
            'Working': 'bg-warning',
            'Testing': 'bg-primary',
            'ReadyForRelease': 'bg-success',
            'Planing': 'bg-info',
            'Specification': 'bg-info',
            'Closed': 'bg-dark',
        }
        color = status_colors.get(value, 'bg-secondary')
        
        return format_html(
            '<span class="badge {}">{}</span>',
            color,
            display_text
        )
    
    def render_organisation(self, value, record):
        """
        Render organisation column with em dash for empty values.
        """
        if record.organisation:
            return record.organisation.name
        return format_html('<span class="text-muted">{}</span>', '—')
    
    def render_assigned_to(self, value, record):
        """
        Render assigned_to column with em dash for empty values.
        """
        if record.assigned_to:
            return record.assigned_to.username
        return format_html('<span class="text-muted">{}</span>', '—')
