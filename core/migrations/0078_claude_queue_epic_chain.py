"""Hierarchical epic/sub structure for the Claude queue (#1079).

Adds the parent/child relation, the frozen order and the entry kind that turn
the flat queue into the orchestrator of the #1076 epic-branch workflow. Purely
additive: every existing row keeps ``kind='issue'``, ``parent_job=None`` and
``epic_order=0``, which is exactly the flat behaviour it had before.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0077_per_user_claude_auth'),
    ]

    operations = [
        migrations.AddField(
            model_name='claudequeuejob',
            name='kind',
            field=models.CharField(
                choices=[('issue', 'Issue run'), ('epic', 'Epic orchestration')],
                default='issue',
                help_text='Issue run (executes Claude) or epic node (orchestrates a chain of sub-entries)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='claudequeuejob',
            name='parent_job',
            field=models.ForeignKey(
                blank=True,
                help_text='Epic node this entry belongs to; null for a standalone run',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sub_jobs',
                to='core.claudequeuejob',
            ),
        ),
        migrations.AddField(
            model_name='claudequeuejob',
            name='epic_order',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Position of this entry inside its epic chain (ascending; ties break by item id)',
            ),
        ),
        migrations.AlterField(
            model_name='claudequeuejob',
            name='status',
            field=models.CharField(
                choices=[
                    ('blocked', 'Blocked (waiting in epic chain)'),
                    ('queued', 'Queued'),
                    ('running', 'Running'),
                    ('orchestrating', 'Orchestrating epic'),
                    ('waiting_limit', 'Waiting for quota'),
                    ('done', 'Done'),
                    ('failed', 'Failed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='queued',
                max_length=20,
            ),
        ),
    ]
