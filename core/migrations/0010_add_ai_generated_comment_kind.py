# Generated migration for adding AI_GENERATED to CommentKind choices

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_add_github_metadata_to_attachment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itemcomment',
            name='kind',
            field=models.CharField(
                choices=[
                    ('Note', 'Note'),
                    ('Comment', 'Comment'),
                    ('EmailIn', 'Email In'),
                    ('EmailOut', 'Email Out'),
                    ('AIGenerated', '🤖 AI Generated'),
                ],
                default='Comment',
                max_length=20
            ),
        ),
    ]
