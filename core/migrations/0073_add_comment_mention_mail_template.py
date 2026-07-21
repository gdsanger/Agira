# Generated migration for adding 'comment-mention' mail template

from django.db import migrations


def add_comment_mention_mail_template(apps, schema_editor):
    """Add mail template for @mention notifications on item comments."""
    MailTemplate = apps.get_model('core', 'MailTemplate')

    MailTemplate.objects.create(
        key='comment-mention',
        subject='Sie wurden erwähnt: {{ issue.title }}',
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
                            <h2 style="margin: 0; font-size: 24px;">Sie wurden in einem Kommentar erwähnt</h2>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 30px;">
                            <p style="margin: 0 0 15px 0; font-size: 14px;">Hallo {{ recipient_name }},</p>

                            <p style="margin: 0 0 20px 0; font-size: 14px;">{{ comment.author }} hat Sie in einem Kommentar zu folgendem Item erwähnt:</p>

                            <!-- Details Box -->
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-left: 4px solid #007bff; margin: 20px 0;">
                                <tr>
                                    <td style="padding: 20px;">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Item:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;"><strong>{{ issue.title }}</strong></td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; vertical-align: top; font-weight: bold; width: 40%; font-size: 14px;">Projekt:</td>
                                                <td style="padding: 8px 0; vertical-align: top; font-size: 14px;">{{ issue.project }}</td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 8px 0; font-size: 14px; font-weight: bold;">Kommentar:</p>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-left: 4px solid #6c757d; margin: 0 0 20px 0;">
                                <tr>
                                    <td style="padding: 15px; font-size: 14px; white-space: pre-wrap;">{{ comment.body|linebreaksbr }}</td>
                                </tr>
                            </table>

                            <!-- Button -->
                            <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 20px 0;">
                                <tr>
                                    <td style="background-color: #007bff; text-align: center;">
                                        <a href="{{ issue.link }}" style="background-color: #007bff; color: #ffffff; padding: 12px 24px; text-decoration: none; display: block; font-size: 14px; font-weight: bold;">Kommentar anzeigen</a>
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


def remove_comment_mention_mail_template(apps, schema_editor):
    """Remove mail template for @mention notifications."""
    MailTemplate = apps.get_model('core', 'MailTemplate')
    MailTemplate.objects.filter(key='comment-mention').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0072_itemcomment_mentioned_users'),
    ]

    operations = [
        migrations.RunPython(add_comment_mention_mail_template, remove_comment_mention_mail_template),
    ]
