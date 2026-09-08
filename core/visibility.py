"""User-scoped visibility filters for the UserUI (#1248).

Agira grows a project per repository, so after a while every list in the UserUI
shows work nobody on the current screen cares about. `Project.members` records
which projects are relevant for which user; the helpers below turn that
assignment into queryset filters.

This is *not* authorization. Nothing here decides what a user may do — only what
the UI puts in front of them. Detail views, POST endpoints and the machine APIs
keep working on the full data set on purpose; a link someone was sent still
opens. Keep it that way: the moment one of these helpers is used to reject a
request, it stops being a visibility filter and becomes a permission system that
nobody reviewed as one.

Semantics are strict: no assignment means no projects, hence no items. The
accompanying migration backfills every existing user with every existing project
so the switch is behaviour-neutral, and `project_create` assigns the creator.
"""
from .models import Item, Project


def _is_authenticated(user):
    return user is not None and getattr(user, 'is_authenticated', False)


def scope_projects(queryset, user):
    """Restrict a Project queryset to the projects assigned to `user`."""
    if not _is_authenticated(user):
        return queryset.none()
    return queryset.filter(members=user)


def scope_items(queryset, user):
    """Restrict an Item queryset to items whose project is assigned to `user`.

    Item visibility is derived, never stored: an item is visible exactly when
    its project is.
    """
    if not _is_authenticated(user):
        return queryset.none()
    return queryset.filter(project__members=user)


def visible_projects_for(user):
    """Projects the given user should see in the UserUI, ordered by name."""
    return scope_projects(Project.objects.all(), user).order_by('name')


def visible_items_for(user):
    """Items the given user should see in the UserUI."""
    return scope_items(Item.objects.all(), user)
