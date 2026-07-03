"""
Inbound webhooks from external systems.

Unlike the rest of the app, these endpoints are called by external services
(GitHub), not by logged-in users, so they authenticate via a shared secret
instead of a session.
"""
import json
import logging

from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import GitHubConfiguration
from .services.github.service import GitHubService
from .services.github.webhook import verify_signature

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def github_pull_request_webhook(request):
    """
    Receive a GitHub `pull_request` webhook event.

    Configured per-repo in GitHub (Settings → Webhooks → this URL, event
    `Pull requests`), not org-wide. Every request must carry a valid
    `X-Hub-Signature-256`, computed by GitHub over the raw body with the
    secret in `GitHubConfiguration.webhook_secret` — without it, requests
    are dropped unprocessed since this is otherwise an unauthenticated,
    state-changing endpoint reachable from the public internet.
    """
    secret = GitHubConfiguration.load().webhook_secret
    signature = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')

    if not verify_signature(secret, request.body, signature):
        logger.warning("Rejected GitHub webhook delivery: invalid or missing signature")
        return HttpResponseForbidden("Invalid signature")

    event = request.META.get('HTTP_X_GITHUB_EVENT', '')
    if event != 'pull_request':
        # Ack so GitHub doesn't retry; only pull_request events do anything here.
        return JsonResponse({'ignored': True, 'event': event})

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid JSON")

    action = payload.get('action')
    pull_request_data = payload.get('pull_request')
    if not pull_request_data:
        return HttpResponseBadRequest("Missing pull_request payload")

    # GitHub fires `pull_request` for many actions (opened, synchronize,
    # labeled, ready_for_review, closed-without-merge, ...). Only a merge
    # is business-relevant here; everything else is acked and dropped so it
    # can't touch item status or mapping/job state.
    if action != 'closed' or not pull_request_data.get('merged'):
        logger.info(
            f"Ignoring GitHub pull_request webhook: action={action!r}, "
            f"merged={pull_request_data.get('merged')!r}"
        )
        return JsonResponse({'ignored': True, 'event': event, 'action': action})

    result = GitHubService().apply_pr_webhook_event(pull_request_data)
    return JsonResponse(result)
