"""Per-user MCP tokens with rotation tracking (#1119).

Adds ``mcp_token_last_rotated`` and backfills the personal token for every
existing user that still has none, so the connector URL in the profile works
for everyone right after deploy without an admin having to hand out tokens.
The rotation date is stamped for all users that carry a token — including the
ones that already had one — so the monthly soft nudge starts from this deploy
instead of firing immediately for everybody.
"""

import secrets

from django.db import migrations, models
from django.utils import timezone


def backfill_mcp_tokens(apps, schema_editor):
    User = apps.get_model('core', 'User')
    now = timezone.now()
    existing = set(
        User.objects.exclude(mcp_token=None).values_list('mcp_token', flat=True)
    )

    to_update = []
    for user in User.objects.all():
        if not user.mcp_token:
            token = secrets.token_urlsafe(32)
            while token in existing:  # `mcp_token` is unique
                token = secrets.token_urlsafe(32)
            existing.add(token)
            user.mcp_token = token
        user.mcp_token_last_rotated = now
        to_update.append(user)

    if to_update:
        User.objects.bulk_update(to_update, ['mcp_token', 'mcp_token_last_rotated'])


def clear_rotation_dates(apps, schema_editor):
    """Reverse: drop the rotation dates, keep the tokens (they are in use)."""
    User = apps.get_model('core', 'User')
    User.objects.update(mcp_token_last_rotated=None)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0078_claude_queue_epic_chain'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='mcp_token_last_rotated',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    'When the MCP token was last generated or rotated. Drives the '
                    'soft reminder to rotate it monthly.'
                ),
            ),
        ),
        migrations.RunPython(backfill_mcp_tokens, clear_rotation_dates),
    ]
