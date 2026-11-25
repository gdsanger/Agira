"""
Change endpoints of the CustomGPT/MCP API (/api/customgpt/...).

Covers reading, creating and editing Changes plus linking items to a change.
Deliberately NOT exposed: deleting a change and everything around approvals
(deciding, adding/removing approvers, sending approval mails). Approvals are a
human decision; the API only shows their state read-only. Approvers are
assigned automatically from the ChangePolicy, exactly as in the web UI.
"""
import json
import logging

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt

from core.models import Change, ChangeStatus, Item, Organisation, Project, Release, RiskLevel
from core.services.activity import ActivityService
from core.services.change_policy_service import ChangePolicyService
from core.views_api import resolve_mcp_user

logger = logging.getLogger(__name__)

TEXT_FIELDS = (
    'title', 'description', 'risk_description', 'mitigation',
    'rollback_plan', 'communication_plan',
)
DATETIME_FIELDS = ('planned_start', 'planned_end', 'executed_at')


def serialize_change(change, detail=False):
    """Serialize a Change. ``detail`` adds long texts, items and approvals."""
    data = {
        'id': change.id,
        'title': change.title,
        'project_id': change.project_id,
        'status': change.status,
        'risk': change.risk,
        'release_id': change.release_id,
        'is_safety_relevant': change.is_safety_relevant,
        'planned_start': change.planned_start.isoformat() if change.planned_start else None,
        'planned_end': change.planned_end.isoformat() if change.planned_end else None,
        'planned_date': change.planned_date.isoformat() if change.planned_date else None,
        'executed_at': change.executed_at.isoformat() if change.executed_at else None,
        'created_by_id': change.created_by_id,
        'created_at': change.created_at.isoformat() if change.created_at else None,
        'updated_at': change.updated_at.isoformat() if change.updated_at else None,
    }
    if detail:
        for field in TEXT_FIELDS[1:]:
            data[field] = getattr(change, field)
        data['organisation_ids'] = list(change.organisations.values_list('id', flat=True))
        data['item_ids'] = list(change.items.values_list('id', flat=True))
        data['associated_item_ids'] = list(change.get_associated_items().values_list('id', flat=True))
        data['approvals'] = [
            {
                'id': a.id,
                'approver_id': a.approver_id,
                'approver_name': a.approver.name,
                'role': a.role,
                'is_required': a.is_required,
                'status': a.status,
                'decision_at': a.decision_at.isoformat() if a.decision_at else None,
                'comment': a.comment,
            }
            for a in change.approvals.select_related('approver')
        ]
    return data


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None, JsonResponse({'error': 'Invalid JSON payload'}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({'error': 'JSON object expected'}, status=400)
    return data, None


def _apply_fields(change, data):
    """Apply payload fields to ``change``. Returns an error string or None."""
    for field in TEXT_FIELDS:
        if field in data:
            if data[field] is None:
                if field == 'title':
                    return 'title must not be empty'
                data[field] = ''
            change.__setattr__(field, str(data[field]))
    if 'status' in data:
        if data['status'] not in ChangeStatus.values:
            return f"Invalid status. Allowed: {', '.join(ChangeStatus.values)}"
        change.status = data['status']
    if 'risk' in data:
        if data['risk'] not in RiskLevel.values:
            return f"Invalid risk. Allowed: {', '.join(RiskLevel.values)}"
        change.risk = data['risk']
    if 'is_safety_relevant' in data:
        change.is_safety_relevant = bool(data['is_safety_relevant'])
    for field in DATETIME_FIELDS:
        if field in data:
            if data[field] in (None, ''):
                setattr(change, field, None)
            else:
                value = parse_datetime(str(data[field]))
                if value is None:
                    return f'{field} must be an ISO 8601 datetime, e.g. 2026-12-01T09:00:00+01:00'
                setattr(change, field, value)
    if 'planned_date' in data:
        if data['planned_date'] in (None, ''):
            change.planned_date = None
        else:
            value = parse_date(str(data['planned_date']))
            if value is None:
                return 'planned_date must be an ISO date, e.g. 2026-12-01'
            change.planned_date = value
    if 'release_id' in data:
        if data['release_id'] in (None, ''):
            change.release = None
        else:
            try:
                change.release = Release.objects.get(id=data['release_id'])
            except (Release.DoesNotExist, ValueError, TypeError):
                return 'Invalid release_id'
    return None


def _set_organisations(change, data):
    """Returns an error string or None."""
    if 'organisation_ids' not in data:
        return None
    ids = data['organisation_ids'] or []
    if not isinstance(ids, list):
        return 'organisation_ids must be a list of ids'
    found = set(Organisation.objects.filter(id__in=ids).values_list('id', flat=True))
    missing = [i for i in ids if i not in found]
    if missing:
        return f'Unknown organisation ids: {missing}'
    change.organisations.set(ids)
    return None


def _sync_approvers(change):
    try:
        ChangePolicyService.sync_change_approvers(change)
    except Exception:
        logger.error('Error syncing approvers for change %s', change.id, exc_info=True)


@csrf_exempt
def api_changes_list(request):
    """GET /changes?project_id=&status=&release_id=&open_only= — list changes (newest first)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    qs = Change.objects.all()
    if request.GET.get('project_id'):
        qs = qs.filter(project_id=request.GET['project_id'])
    if request.GET.get('release_id'):
        qs = qs.filter(release_id=request.GET['release_id'])
    status = request.GET.get('status')
    if status:
        if status not in ChangeStatus.values:
            return JsonResponse({'error': f"Invalid status. Allowed: {', '.join(ChangeStatus.values)}"}, status=400)
        qs = qs.filter(status=status)
    if request.GET.get('open_only', '').lower() in ('1', 'true', 'yes'):
        qs = qs.exclude(status__in=[ChangeStatus.DEPLOYED, ChangeStatus.ROLLED_BACK, ChangeStatus.CANCELED])
    return JsonResponse([serialize_change(c) for c in qs[:200]], safe=False)


@csrf_exempt
def api_change_detail_handler(request, change_id):
    """GET/PATCH/PUT /changes/{id}."""
    try:
        change = Change.objects.get(id=change_id)
    except Change.DoesNotExist:
        return JsonResponse({'error': 'Change not found'}, status=404)
    if request.method == 'GET':
        return JsonResponse(serialize_change(change, detail=True))
    if request.method not in ('PATCH', 'PUT'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    data, err = _json_body(request)
    if err:
        return err
    if 'project_id' in data and data['project_id'] != change.project_id:
        return JsonResponse({'error': 'project_id of an existing change cannot be changed'}, status=400)
    msg = _apply_fields(change, data)
    if msg:
        return JsonResponse({'error': msg}, status=400)
    try:
        change.full_clean()
        change.save()
    except ValidationError as e:
        return JsonResponse({'error': '; '.join(e.messages)}, status=400)
    msg = _set_organisations(change, data)
    if msg:
        return JsonResponse({'error': msg}, status=400)
    _sync_approvers(change)
    ActivityService().log(
        verb='change.updated', target=change, actor=resolve_mcp_user(request),
        summary=f'Change "{change.title}" was updated via MCP',
    )
    return JsonResponse(serialize_change(change, detail=True))


@csrf_exempt
def api_project_create_change(request, project_id):
    """POST /projects/{project_id}/changes — create a change (status defaults to Draft)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)
    data, err = _json_body(request)
    if err:
        return err
    if not str(data.get('title') or '').strip():
        return JsonResponse({'error': 'title is required'}, status=400)
    user = resolve_mcp_user(request)
    change = Change(project=project, created_by=user)
    msg = _apply_fields(change, data)
    if msg:
        return JsonResponse({'error': msg}, status=400)
    try:
        change.full_clean()
        change.save()
    except ValidationError as e:
        return JsonResponse({'error': '; '.join(e.messages)}, status=400)
    msg = _set_organisations(change, data)
    if msg:
        change.delete()
        return JsonResponse({'error': msg}, status=400)
    item_ids = data.get('item_ids') or []
    if item_ids:
        change.items.add(*Item.objects.filter(id__in=item_ids))
    _sync_approvers(change)
    ActivityService().log(
        verb='change.created', target=change, actor=user,
        summary=f'Change "{change.title}" was created via MCP',
    )
    return JsonResponse(serialize_change(change, detail=True), status=201)


@csrf_exempt
def api_change_items(request, change_id):
    """POST /changes/{id}/items — body {add_item_ids: [], remove_item_ids: []}."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        change = Change.objects.get(id=change_id)
    except Change.DoesNotExist:
        return JsonResponse({'error': 'Change not found'}, status=404)
    data, err = _json_body(request)
    if err:
        return err
    add_ids = data.get('add_item_ids') or []
    remove_ids = data.get('remove_item_ids') or []
    if not isinstance(add_ids, list) or not isinstance(remove_ids, list):
        return JsonResponse({'error': 'add_item_ids / remove_item_ids must be lists of item ids'}, status=400)
    to_add = list(Item.objects.filter(id__in=add_ids))
    unknown = set(add_ids) - {i.id for i in to_add}
    if unknown:
        return JsonResponse({'error': f'Unknown item ids: {sorted(unknown)}'}, status=400)
    change.items.add(*to_add)
    if remove_ids:
        change.items.remove(*Item.objects.filter(id__in=remove_ids))
    ActivityService().log(
        verb='change.items_updated', target=change, actor=resolve_mcp_user(request),
        summary=f'Items of change "{change.title}" updated via MCP (+{len(to_add)}/-{len(remove_ids)})',
    )
    return JsonResponse(serialize_change(change, detail=True))


@csrf_exempt
def api_project_releases(request, project_id):
    """GET /projects/{project_id}/releases — releases a change can be attached to."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not Project.objects.filter(id=project_id).exists():
        return JsonResponse({'error': 'Project not found'}, status=404)
    releases = Release.objects.filter(project_id=project_id)
    return JsonResponse([
        {
            'id': r.id, 'name': r.name, 'version': r.version, 'status': r.status,
            'planned_date': r.planned_date.isoformat() if r.planned_date else None,
        }
        for r in releases
    ], safe=False)


@csrf_exempt
def api_organisations_list(request):
    """GET /organisations — organisations that can be assigned to a change."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    return JsonResponse(
        [{'id': o.id, 'name': o.name} for o in Organisation.objects.order_by('name')], safe=False
    )
