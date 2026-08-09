"""Split the generic "Opus" model choice into Opus 4.8 / Opus 5, add Fable 5 (#1082).

Existing rows carry the generic ``opus`` slug, which the worker used to pass to
the CLI as the floating ``opus`` alias. That alias resolved to Opus 4.8 in
practice, so mapping the old value onto ``opus-4-8`` preserves what those items
were actually running.
"""

from django.db import migrations, models

_LEGACY_OPUS = 'opus'
_OPUS_4_8 = 'opus-4-8'

_TARGETS = (
    ('Item', 'suggested_model'),
    ('ClaudeQueueJob', 'model'),
)


def opus_to_opus_4_8(apps, schema_editor):
    for model_name, field in _TARGETS:
        model = apps.get_model('core', model_name)
        model.objects.filter(**{field: _LEGACY_OPUS}).update(**{field: _OPUS_4_8})


def opus_4_8_to_opus(apps, schema_editor):
    """Fold both new Opus generations (and Fable) back onto the generic slug.

    Reversing is lossy — the old field had no way to express the distinction —
    so everything above Sonnet collapses to ``opus``, mirroring the pre-#1082
    state where any Opus-class job ran on the floating alias.
    """
    for model_name, field in _TARGETS:
        model = apps.get_model('core', model_name)
        model.objects.filter(
            **{f'{field}__in': [_OPUS_4_8, 'opus-5', 'fable-5']}
        ).update(**{field: _LEGACY_OPUS})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0074_claudequeuejob_allow_api_key_fallback_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='claudequeuejob',
            name='model',
            field=models.CharField(
                choices=[
                    ('sonnet', 'Sonnet'),
                    ('opus-4-8', 'Opus 4.8'),
                    ('opus-5', 'Opus 5'),
                    ('fable-5', 'Fable 5'),
                ],
                default='sonnet',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='item',
            name='suggested_model',
            field=models.CharField(
                choices=[
                    ('sonnet', 'Sonnet'),
                    ('opus-4-8', 'Opus 4.8'),
                    ('opus-5', 'Opus 5'),
                    ('fable-5', 'Fable 5'),
                ],
                default='sonnet',
                help_text='AI-suggested Claude model for automated processing. A suggestion, not a gate — overridable in the UI.',
                max_length=20,
            ),
        ),
        migrations.RunPython(opus_to_opus_4_8, opus_4_8_to_opus),
    ]
