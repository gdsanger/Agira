from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0067_claudequeuejob_pr_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='externalissuemapping',
            name='pr_body',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Final PR description captured at merge (indexed into Weaviate as RAG context)',
            ),
        ),
        migrations.AddField(
            model_name='externalissuemapping',
            name='merge_commit_sha',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Merge commit SHA from the merge webhook (for Chunk -> Commit back-linking)',
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name='externalissuemapping',
            name='merged_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='When the PR was merged (from the merge webhook payload)',
            ),
        ),
    ]
