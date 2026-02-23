# Generated migration for adding CHANGE_FILE role to AttachmentRole

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0059_make_change_timestamps_editable'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attachmentlink',
            name='role',
            field=models.CharField(
                choices=[
                    ('ProjectFile', 'Project File'),
                    ('ItemFile', 'Item File'),
                    ('ChangeFile', 'Change File'),
                    ('CommentAttachment', 'Comment Attachment'),
                    ('ApproverAttachment', 'Approver Attachment'),
                    ('transkript', 'Meeting Transcript'),
                ],
                max_length=30,
            ),
        ),
    ]
