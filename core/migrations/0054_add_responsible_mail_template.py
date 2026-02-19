# Generated migration for adding 'resp' mail template

from django.db import migrations


def add_responsible_mail_template(apps, schema_editor):
    """Add mail template for item responsible assignment notifications."""
    MailTemplate = apps.get_model('core', 'MailTemplate')
    GlobalSettings = apps.get_model('core', 'GlobalSettings')
    
    # Get base_url for generating link
    try:
        settings = GlobalSettings.objects.first()
        base_url = settings.base_url if settings and settings.base_url else 'http://localhost:8000'
    except:
        base_url = 'http://localhost:8000'
    
    MailTemplate.objects.create(
        key='resp',
        subject='Item zugewiesen: {{ issue.title }}',
        message='''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #007bff; color: white; padding: 15px; text-align: center; }
        .content { background-color: #f8f9fa; padding: 20px; margin-top: 10px; }
        .details { background-color: white; padding: 15px; border-left: 4px solid #007bff; margin: 15px 0; }
        .details table { width: 100%; border-collapse: collapse; }
        .details td { padding: 8px 0; vertical-align: top; }
        .details td:first-child { font-weight: bold; width: 40%; }
        .button { background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; display: inline-block; margin: 15px 0; border-radius: 4px; }
        .footer { margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Item wurde Ihnen zugewiesen</h2>
        </div>
        
        <div class="content">
            <p>Hallo {{ issue.responsible }},</p>
            
            <p>das folgende Item wurde Ihnen als verantwortliche Person zugewiesen:</p>
            
            <div class="details">
                <table>
                    <tr>
                        <td>Titel:</td>
                        <td><strong>{{ issue.title }}</strong></td>
                    </tr>
                    <tr>
                        <td>Typ:</td>
                        <td>{{ issue.type }}</td>
                    </tr>
                    <tr>
                        <td>Projekt:</td>
                        <td>{{ issue.project }}</td>
                    </tr>
                    <tr>
                        <td>Verantwortlich:</td>
                        <td>{{ issue.responsible }}</td>
                    </tr>
                    <tr>
                        <td>Zugewiesen an:</td>
                        <td>{% if issue.assigned_to %}{{ issue.assigned_to }}{% else %}<em>—</em>{% endif %}</td>
                    </tr>
                    <tr>
                        <td>Requester:</td>
                        <td>{{ issue.requester }}</td>
                    </tr>
                    <tr>
                        <td>Status:</td>
                        <td>{{ issue.status }}</td>
                    </tr>
                </table>
            </div>
            
            <p>
                <a href="{{ issue.link }}" class="button">Item anzeigen</a>
            </p>
            
            <p>Mit freundlichen Grüßen<br>
            Agira Team</p>
        </div>
        
        <div class="footer">
            <p>Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht direkt auf diese Nachricht.</p>
        </div>
    </div>
</body>
</html>''',
        from_name='Agira',
        from_address='',
        cc_address='',
        is_active=True
    )


def remove_responsible_mail_template(apps, schema_editor):
    """Remove mail template for responsible assignment notifications."""
    MailTemplate = apps.get_model('core', 'MailTemplate')
    MailTemplate.objects.filter(key='resp').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0053_add_item_responsible'),
    ]

    operations = [
        migrations.RunPython(add_responsible_mail_template, remove_responsible_mail_template),
    ]
