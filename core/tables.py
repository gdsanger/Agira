"""
Django tables for Item model.
"""
import django_tables2 as tables
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.urls import reverse
from .models import ClaudeQueueJobModel, Item, ItemStatus, Release, User, UserRole


# Badge colours for the read-only status rendering (customer portal).
ITEM_STATUS_BADGE_CLASSES = {
    'Inbox': 'bg-info',
    'Backlog': 'bg-secondary',
    'Working': 'bg-warning',
    'Testing': 'bg-primary',
    'Review': 'bg-light text-dark',
    'ReadyForRelease': 'bg-success',
    'Closed': 'bg-dark',
}


def render_item_status_badge(value):
    """Render a status value as a read-only badge."""
    display_text = dict(ItemStatus.choices).get(value, value)
    return format_html(
        '<span class="badge {}">{}</span>',
        ITEM_STATUS_BADGE_CLASSES.get(value, 'bg-secondary'),
        display_text,
    )


# Fields the item lists edit inline next to the status (see ``item-list-field``).
LIST_INLINE_FIELDS = ('responsible', 'suggested_model')


def agent_choices():
    """(pk, name) pairs of every user that may be set as responsible (role Agent)."""
    return [
        (str(pk), name)
        for pk, name in User.objects.filter(role=UserRole.AGENT)
        .order_by('name')
        .values_list('pk', 'name')
    ]


def render_item_list_field_cell(item, field, agents=None, error=None, saved=False):
    """Render the inline responsible / suggested-model editor for one list row.

    ``agents`` is the (pk, name) list from :func:`agent_choices`; tables pass it
    in once so a page of rows does not run one agent query per row.
    """
    if field == 'responsible':
        choices = list(agents if agents is not None else agent_choices())
        current = str(item.responsible_id) if item.responsible_id else ''
        # Keep a responsible that is no longer an agent visible instead of
        # silently showing "—" for it.
        if current and current not in {value for value, _ in choices}:
            choices.insert(0, (current, item.responsible.name))
        allow_empty = True
    elif field == 'suggested_model':
        choices = ClaudeQueueJobModel.choices
        current = item.suggested_model or ''
        allow_empty = False
    else:
        raise ValueError(f'Field "{field}" is not editable in item lists.')

    return render_to_string(
        'partials/item_list_field_cell.html',
        {
            'item': item,
            'field': field,
            'choices': choices,
            'current': current,
            'allow_empty': allow_empty,
            'field_error': error,
            'field_saved': saved,
        },
    )


class ItemListColumnsMixin(tables.Table):
    """Shared ID and inline-editable status columns for every internal item list (#1249).

    Lives in one place so the root lists (``/items/{status}/``) and the nested ones
    (related items, release items) show the same visible ID, the same status and the
    same inline editor instead of drifting apart. The status select posts to the
    mail-free ``item-list-status`` endpoint - the DetailView mail flow stays out of
    lists entirely.

    Not applied to :class:`EmbedItemTable`: the customer portal is read-only and
    unauthenticated, so it keeps its status badge.
    """

    id = tables.Column(
        verbose_name='ID',
        orderable=True,
        attrs={
            'td': {'class': 'text-muted small'},
            'th': {'style': 'width: 70px;'},
        },
    )

    status = tables.Column(
        verbose_name='Status',
        orderable=True,
        attrs={'td': {'class': 'item-status-cell-td'}, 'th': {'style': 'width: 180px;'}},
    )

    responsible = tables.Column(
        verbose_name='Responsible',
        orderable=True,
        accessor='responsible__name',
        empty_values=(),
        attrs={'td': {'class': 'item-list-field-cell-td'}, 'th': {'style': 'width: 170px;'}},
    )

    suggested_model = tables.Column(
        verbose_name='Suggested Model',
        orderable=True,
        attrs={'td': {'class': 'item-list-field-cell-td'}, 'th': {'style': 'width: 140px;'}},
    )

    def render_responsible(self, record):
        """Render the inline responsible editor (agents only, like the DetailView)."""
        if not hasattr(self, '_agent_choices'):
            self._agent_choices = agent_choices()
        return render_item_list_field_cell(record, 'responsible', agents=self._agent_choices)

    def render_suggested_model(self, record):
        """Render the inline suggested-model editor."""
        return render_item_list_field_cell(record, 'suggested_model')

    def render_id(self, value):
        """Render the item ID as a `#123` prefix - visible text, not just a link target."""
        return format_html('<span class="text-muted">#{}</span>', value)

    def render_status(self, record):
        """Render the shared inline status editor fragment."""
        return render_to_string(
            'partials/item_status_cell.html',
            {'item': record, 'status_choices': ItemStatus.choices},
        )


class ItemTable(ItemListColumnsMixin, tables.Table):
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
    
    # Requester column
    requester = tables.Column(
        verbose_name='Requester',
        orderable=True,
        accessor='requester__username',
        attrs={'td': {'class': 'small'}},
        empty_values=()
    )
    
    # Comments column (annotated comment_count, no per-row query)
    comments = tables.Column(
        verbose_name='Comments',
        orderable=True,
        accessor='comment_count',
        empty_values=(),
        attrs={'td': {'class': 'text-center', 'style': 'width: 60px;'}}
    )

    # Actions column (delete button with HTMX)
    actions = tables.Column(
        verbose_name='Actions',
        orderable=False,
        empty_values=(),
        attrs={'td': {'class': 'text-end', 'style': 'width: 80px;'}}
    )
    
    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('id', 'updated_at', 'title', 'type', 'status', 'project', 'requester', 'responsible', 'suggested_model', 'comments', 'actions')
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
    
    def render_requester(self, value, record):
        """
        Render requester column with em dash for empty values.
        """
        if record.requester:
            return record.requester.username
        return format_html('<span class="text-muted">{}</span>', '—')

    def render_comments(self, record):
        """
        Render comment count badge. Relies on the comment_count annotation
        added in the view queryset - renders nothing for 0 comments so an
        item without comments never shows a false-positive indicator.
        """
        count = getattr(record, 'comment_count', 0) or 0
        if not count:
            return ''
        return format_html(
            '<span class="badge bg-light text-dark border" title="{} comment{}">'
            '<i class="bi bi-chat-left-text"></i> {}</span>',
            count,
            '' if count == 1 else 's',
            count
        )

    def render_actions(self, record):
        """
        Render actions column with delete button using HTMX.
        """
        delete_url = reverse('item-list-delete', kwargs={'item_id': record.id})
        
        return format_html(
            '<button type="button" '
            'class="btn btn-sm btn-outline-danger" '
            'hx-post="{}" '
            'hx-confirm="Are you sure you want to delete this item?" '
            'hx-target="#items-list-container" '
            'hx-swap="outerHTML" '
            'title="Delete item">'
            '<i class="bi bi-trash"></i>'
            '</button>',
            delete_url
        )


class RelatedItemsTable(ItemListColumnsMixin, tables.Table):
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

    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('id', 'updated_at', 'title', 'type', 'status', 'responsible', 'suggested_model')
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
        Render status column as a read-only badge.

        The customer portal stays read-only: it is unauthenticated, so it never
        gets the inline status editor the internal lists use.
        """
        return render_item_status_badge(value)

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


class ReleaseItemsTable(ItemListColumnsMixin, tables.Table):
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

    class Meta:
        model = Item
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('id', 'updated_at', 'title', 'type', 'status', 'responsible', 'suggested_model')
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



class IssueBlueprintTable(tables.Table):
    """
    Table for displaying IssueBlueprint list with sortable columns.
    """
    
    # Title column with link to detail view
    title = tables.Column(
        verbose_name='Title',
        orderable=True,
        attrs={'td': {'class': 'blueprint-title-cell'}}
    )
    
    # Category column
    category = tables.Column(
        verbose_name='Category',
        orderable=True,
        accessor='category__name'
    )
    
    # Active column
    is_active = tables.BooleanColumn(
        verbose_name='Active',
        orderable=True,
        yesno='✓,✗'
    )
    
    # Version column
    version = tables.Column(
        verbose_name='Version',
        orderable=True,
        attrs={'td': {'class': 'text-center small'}}
    )
    
    # Updated at column
    updated_at = tables.DateTimeColumn(
        verbose_name='Updated',
        format='Y-m-d H:i',
        orderable=True,
        attrs={'td': {'class': 'text-muted small'}}
    )
    
    # Tags column
    tags = tables.Column(
        verbose_name='Tags',
        orderable=False,
        empty_values=(),
        attrs={'td': {'class': 'small'}}
    )
    
    # Actions column
    actions = tables.Column(
        verbose_name='Actions',
        orderable=False,
        empty_values=(),
        attrs={'td': {'class': 'text-end', 'style': 'width: 120px;'}}
    )
    
    class Meta:
        from .models import IssueBlueprint
        model = IssueBlueprint
        template_name = 'django_tables2/bootstrap5.html'
        fields = ('title', 'category', 'is_active', 'version', 'updated_at', 'tags', 'actions')
        attrs = {
            'class': 'table table-hover',
            'thead': {'class': 'table-light'}
        }
        order_by = '-updated_at'
    
    def render_title(self, record):
        """
        Render title column with link to detail view.
        """
        url = reverse('blueprint-detail', kwargs={'id': str(record.id)})
        title_html = format_html(
            '<a href="{}" class="text-decoration-none"><strong>{}</strong></a>',
            url,
            record.title
        )
        
        if record.description_md:
            # Truncate description to 10 words
            words = record.description_md.split()
            truncated = ' '.join(words[:10])
            if len(words) > 10:
                truncated += '...'
            desc_html = format_html(
                '<br><small class="text-muted">{}</small>',
                truncated
            )
            return format_html('{}{}', title_html, desc_html)
        
        return title_html
    
    def render_category(self, record):
        """
        Render category column as a badge.
        """
        return format_html(
            '<span class="badge bg-info">{}</span>',
            record.category.name
        )
    
    def render_tags(self, value, record):
        """
        Render tags column as compact badges.
        """
        if record.tags and len(record.tags) > 0:
            # Show first 2 tags + count if more
            tags_html = []
            for i, tag in enumerate(record.tags[:2]):
                tags_html.append(format_html(
                    '<span class="badge bg-secondary me-1">{}</span>',
                    tag
                ))
            if len(record.tags) > 2:
                tags_html.append(format_html(
                    '<span class="text-muted">+{}</span>',
                    len(record.tags) - 2
                ))
            return format_html('{}', mark_safe(''.join(str(h) for h in tags_html)))
        return format_html('<span class="text-muted">{}</span>', '—')
    
    def render_actions(self, record):
        """
        Render actions column with view and edit buttons.
        """
        view_url = reverse('blueprint-detail', kwargs={'id': str(record.id)})
        edit_url = reverse('blueprint-edit', kwargs={'id': str(record.id)})
        
        return format_html(
            '<a href="{}" class="btn btn-sm btn-outline-primary me-1" title="View">'
            '<i class="bi bi-eye"></i></a>'
            '<a href="{}" class="btn btn-sm btn-outline-secondary" title="Edit">'
            '<i class="bi bi-pencil"></i></a>',
            view_url,
            edit_url
        )
