"""
Item copy service.

Creates a copy of an item in another project. Typical use: one reported
problem affects several projects and needs one own issue per project. The
original item is never modified (except for the relation link added to it).

What is copied
    title, description, user_input, type, intern, requester, organisation
    (organisation only if it is a client of the target project),
    suggested_model, implementation_provider, review_provider, claude_auth_mode.

What is deliberately NOT copied (fresh start in the target project)
    status (-> Inbox), assigned_to, responsible, parent / epic_order,
    solution_description, pr_description, short_description, solution_release,
    nodes, changes, comments, attachments, GitHub issue/PR mappings,
    followers. These are project- or work-specific; copying them would
    produce a misleading "already solved" copy.

Original and copy are linked with an ``ItemRelation`` (``Related``,
copy -> original) so the connection stays visible on both items.
"""
import logging

from django.db import transaction
from django.core.exceptions import ValidationError

from core.models import Item, ItemRelation, ItemStatus, Project, RelationType
from core.services.activity import ActivityService

logger = logging.getLogger(__name__)


class ItemCopyError(Exception):
    """Raised when an item cannot be copied (user-facing message)."""


@transaction.atomic
def copy_item_to_project(item, target_project, actor=None, copy_title_prefix=''):
    """
    Copy ``item`` into ``target_project`` and return the new item.

    Copying into the item's own project is allowed (e.g. to split an item);
    the caller decides whether that makes sense.
    """
    if not isinstance(target_project, Project):
        raise ItemCopyError('Target project is required')

    organisation = item.organisation
    if organisation is not None:
        clients = list(target_project.clients.all())
        # Same rule as when moving: keep the organisation only if the target
        # project explicitly lists it as a client.
        if organisation not in clients:
            organisation = None

    new_item = Item(
        project=target_project,
        title=f'{copy_title_prefix}{item.title}',
        description=item.description,
        user_input=item.user_input,
        type=item.type,
        intern=item.intern,
        requester=item.requester,
        organisation=organisation,
        status=ItemStatus.INBOX,
        suggested_model=item.suggested_model,
        implementation_provider=item.implementation_provider,
        review_provider=item.review_provider,
        claude_auth_mode=item.claude_auth_mode,
    )
    try:
        new_item.full_clean()
    except ValidationError as exc:
        raise ItemCopyError(str(exc)) from exc
    new_item.save()

    ItemRelation.objects.get_or_create(
        from_item=new_item,
        to_item=item,
        relation_type=RelationType.RELATED,
    )

    activity = ActivityService()
    activity.log(
        verb='item.copied',
        target=item,
        actor=actor,
        summary=f'Copied to {target_project.name} as #{new_item.id}',
    )
    activity.log(
        verb='item.created',
        target=new_item,
        actor=actor,
        summary=f'Copy of #{item.id} ({item.project.name})',
    )
    logger.info('Item %s copied to project %s as item %s', item.id, target_project.id, new_item.id)
    return new_item
