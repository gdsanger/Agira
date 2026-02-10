# Generated manually for issue 369 - Approvers refactor

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_add_system_setting_model'),
    ]

    operations = [
        # First, migrate existing Approved/Rejected status values to new ones
        migrations.RunSQL(
            sql="UPDATE core_changeapproval SET status = 'Accept' WHERE status = 'Approved';",
            reverse_sql="UPDATE core_changeapproval SET status = 'Approved' WHERE status = 'Accept';",
        ),
        migrations.RunSQL(
            sql="UPDATE core_changeapproval SET status = 'Reject' WHERE status = 'Rejected';",
            reverse_sql="UPDATE core_changeapproval SET status = 'Rejected' WHERE status = 'Reject';",
        ),
        
        # Update the status field choices to include new values
        migrations.AlterField(
            model_name='changeapproval',
            name='status',
            field=models.CharField(
                choices=[
                    ('Pending', 'Pending'),
                    ('Accept', 'Accept'),
                    ('Reject', 'Reject'),
                    ('Abstained', 'Abstained')
                ],
                default='Pending',
                max_length=20
            ),
        ),
        
        # Remove the informed_at field
        migrations.RemoveField(
            model_name='changeapproval',
            name='informed_at',
        ),
        
        # Remove the approved field
        migrations.RemoveField(
            model_name='changeapproval',
            name='approved',
        ),
    ]
