from django.db import migrations


def create_change_update_mail_templates(apps, schema_editor):
    """Create the change-update-reminder and change-update-completed MailTemplates."""
    MailTemplate = apps.get_model('core', 'MailTemplate')

    if not MailTemplate.objects.filter(key='change-update-reminder').exists():
        MailTemplate.objects.create(
            key='change-update-reminder',
            subject='Update-Erinnerung: {{ change_title }} ({{ change_id }})',
            message='''<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #007bff; color: white; padding: 20px; text-align: center; }
        .content { padding: 20px; background-color: #f8f9fa; }
        .footer { padding: 20px; text-align: center; color: #6c757d; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Update-Erinnerung</h2>
        </div>
        <div class="content">
            <p>Hallo,</p>
            <p>dies ist eine Erinnerung zu folgendem Change:</p>
            <p><strong>Change-ID:</strong> {{ change_id }}</p>
            <p><strong>Titel:</strong> {{ change_title }}</p>
            <p>Bitte beachten Sie das beigefügte Change-PDF für weitere Details.</p>
        </div>
        <div class="footer">
            <p>Diese Nachricht wurde automatisch vom Agira Change Management System gesendet.</p>
        </div>
    </div>
</body>
</html>''',
            is_active=True,
        )

    if not MailTemplate.objects.filter(key='change-update-completed').exists():
        MailTemplate.objects.create(
            key='change-update-completed',
            subject='Update abgeschlossen: {{ change_title }} ({{ change_id }})',
            message='''<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #28a745; color: white; padding: 20px; text-align: center; }
        .content { padding: 20px; background-color: #f8f9fa; }
        .footer { padding: 20px; text-align: center; color: #6c757d; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Update abgeschlossen</h2>
        </div>
        <div class="content">
            <p>Hallo,</p>
            <p>das Update für folgenden Change wurde abgeschlossen:</p>
            <p><strong>Change-ID:</strong> {{ change_id }}</p>
            <p><strong>Titel:</strong> {{ change_title }}</p>
            <p>Bitte beachten Sie das beigefügte Change-PDF für weitere Details.</p>
        </div>
        <div class="footer">
            <p>Diese Nachricht wurde automatisch vom Agira Change Management System gesendet.</p>
        </div>
    </div>
</body>
</html>''',
            is_active=True,
        )


def remove_change_update_mail_templates(apps, schema_editor):
    """Remove the change-update-reminder and change-update-completed MailTemplates."""
    MailTemplate = apps.get_model('core', 'MailTemplate')
    MailTemplate.objects.filter(
        key__in=['change-update-reminder', 'change-update-completed']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0060_add_change_file_attachment_role'),
    ]

    operations = [
        migrations.RunPython(
            create_change_update_mail_templates,
            reverse_code=remove_change_update_mail_templates,
        ),
    ]
