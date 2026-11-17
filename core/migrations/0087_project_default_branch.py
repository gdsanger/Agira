from django.db import migrations, models


class Migration(migrations.Migration):
    # Also merges the two parallel 0086 migrations.
    dependencies = [
        ('core', '0086_claude_queue_completion_confirmed'),
        ('core', '0086_claude_review_override'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='default_branch',
            field=models.CharField(
                blank=True, default='main', max_length=255,
                help_text='Default branch of the GitHub repository (e.g. main or master).',
            ),
        ),
    ]
