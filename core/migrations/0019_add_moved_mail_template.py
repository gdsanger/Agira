# Generated migration for adding 'moved' mail template

from django.db import migrations


def add_moved_mail_template(apps, schema_editor):
    """Add mail template for item move notifications."""
    MailTemplate = apps.get_model('core', 'MailTemplate')
    
    MailTemplate.objects.create(
        key='moved',
        subject='Item verschoben: {{ issue.title }}',
        message='''<p>Hallo,</p>

<p>das Item <strong>"{{ issue.title }}"</strong> wurde in ein anderes Projekt verschoben.</p>

<p><strong>Details:</strong></p>
<ul>
    <li><strong>Neues Projekt:</strong> {{ issue.project }}</li>
    <li><strong>Status:</strong> {{ issue.status }}</li>
    <li><strong>Typ:</strong> {{ issue.type }}</li>
    <li><strong>Zugewiesen an:</strong> {{ issue.assigned_to }}</li>
    <li><strong>Release:</strong> {{ issue.solution_release }}</li>
</ul>

<p><strong>Beschreibung:</strong></p>
<p>{{ issue.description }}</p>

<p>Mit freundlichen Grüßen<br>
Agira Team</p>''',
        from_name='Agira',
        from_address='',
        cc_address='',
        is_active=True
    )


def remove_moved_mail_template(apps, schema_editor):
    """Remove mail template for item move notifications."""
    MailTemplate = apps.get_model('core', 'MailTemplate')
    MailTemplate.objects.filter(key='moved').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_add_azure_ad_object_id'),
    ]

    operations = [
        migrations.RunPython(add_moved_mail_template, remove_moved_mail_template),
    ]
