# Generated migration to remove PLANING and SPECIFICATION statuses

from django.db import migrations, models


def migrate_removed_statuses(apps, schema_editor):
    """
    Migrate items with PLANING or SPECIFICATION status to BACKLOG.
    """
    Item = apps.get_model('core', 'Item')
    MailActionMapping = apps.get_model('core', 'MailActionMapping')
    
    # Migrate Items with removed statuses to Backlog
    Item.objects.filter(status='Planing').update(status='Backlog')
    Item.objects.filter(status='Specification').update(status='Backlog')
    
    # Migrate MailActionMapping with removed statuses to Backlog
    MailActionMapping.objects.filter(item_status='Planing').update(item_status='Backlog')
    MailActionMapping.objects.filter(item_status='Specification').update(item_status='Backlog')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0046_alter_activity_target_object_id'),
    ]

    operations = [
        # First, migrate existing data
        migrations.RunPython(migrate_removed_statuses, migrations.RunPython.noop),
        
        # Then, update the field choices
        migrations.AlterField(
            model_name='item',
            name='status',
            field=models.CharField(
                choices=[
                    ('Inbox', '📥 Inbox'),
                    ('Backlog', '📋 Backlog'),
                    ('Working', '🚧 Working'),
                    ('Testing', '🧪 Testing'),
                    ('ReadyForRelease', '✅ Ready for Release'),
                    ('Closed', '✔ Closed')
                ],
                default='Inbox',
                max_length=20
            ),
        ),
        migrations.AlterField(
            model_name='mailactionmapping',
            name='item_status',
            field=models.CharField(
                choices=[
                    ('Inbox', '📥 Inbox'),
                    ('Backlog', '📋 Backlog'),
                    ('Working', '🚧 Working'),
                    ('Testing', '🧪 Testing'),
                    ('ReadyForRelease', '✅ Ready for Release'),
                    ('Closed', '✔ Closed')
                ],
                help_text='Issue status for which this mapping applies',
                max_length=20
            ),
        ),
    ]
