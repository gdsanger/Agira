"""Add Opus 5.5 and Sonnet 5.5 to the Claude model choices.

Choices-only change: no schema change at the database level and no data
migration — existing items and jobs keep their stored model slug.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0080_project_members"),
    ]

    operations = [
        migrations.AlterField(
            model_name="claudequeuejob",
            name="model",
            field=models.CharField(
                choices=[
                    ("sonnet", "Sonnet"),
                    ("opus-4-8", "Opus 4.8"),
                    ("opus-5", "Opus 5"),
                    ("fable-5", "Fable 5"),
                    ("opus-5-5", "Opus 5.5"),
                    ("sonnet-5-5", "Sonnet 5.5"),
                ],
                default="sonnet",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="item",
            name="suggested_model",
            field=models.CharField(
                choices=[
                    ("sonnet", "Sonnet"),
                    ("opus-4-8", "Opus 4.8"),
                    ("opus-5", "Opus 5"),
                    ("fable-5", "Fable 5"),
                    ("opus-5-5", "Opus 5.5"),
                    ("sonnet-5-5", "Sonnet 5.5"),
                ],
                default="sonnet",
                help_text="AI-suggested Claude model for automated processing. A suggestion, not a gate — overridable in the UI.",
                max_length=20,
            ),
        ),
    ]
