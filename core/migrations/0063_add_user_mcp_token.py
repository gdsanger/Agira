# Generated manually for the Agira MCP connector.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0062_add_user_github_pat'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='mcp_token',
            field=models.CharField(
                blank=True,
                null=True,
                max_length=64,
                unique=True,
                help_text=(
                    'Personal token for the Agira MCP connector (Claude). '
                    'Leave empty to disable MCP access for this user.'
                ),
            ),
        ),
    ]
