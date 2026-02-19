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
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f4f4f4;">
        <tr>
            <td align="center" style="padding: 20px 0;">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #007bff; color: #ffffff; padding: 20px; text-align: center;">
                            <h2 style="margin: 0; font-size: 24px;">Item wurde Ihnen zugewiesen</h2>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 30px;">
                            <p style="margin: 0 0 15px 0; font-size: 14px;">Hallo {{ issue.responsible }},</p>
                            
                            <p style="margin: 0 0 20px 0; font-size: 14px;">das folgende Item wurde Ihnen als verantwortliche Person zugewiesen:</p>
                            
                            <!-- Details Box -->
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-left: 4px solid #007bff; margin: 20px 0;">
                                <tr>
                                    <td style="padding: 20px;">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Titel:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;"><strong>{{ issue.title }}</strong></td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Typ:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{{ issue.type }}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Projekt:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{{ issue.project }}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Verantwortlich:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{{ issue.responsible }}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Zugewiesen an:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{% if issue.assigned_to %}{{ issue.assigned_to }}{% else %}<em>—</em>{% endif %}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Requester:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{{ issue.requester }}</td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Status:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{{ issue.status }}</td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Button -->
                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 20px 0;">
                                <tr>
                                    <td style="background-color: #007bff; text-align: center;">
                                        <a href="{{ issue.link }}" style="background-color: #007bff; color: #ffffff; padding: 12px 24px; text-decoration: none; display: block; font-size: 14px; font-weight: bold;">Item anzeigen</a>
                                    </td>
                                </tr>
                            </table>
                            
                            <p style="margin: 20px 0 0 0; font-size: 14px;">Mit freundlichen Grüßen<br>Agira Team</p>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #ffffff; padding: 20px; text-align: center; border-top: 1px solid #dddddd;">
                            <p style="margin: 0; font-size: 12px; color: #666666;">Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht direkt auf diese Nachricht.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
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
