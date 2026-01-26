# GitHub Workers Documentation

Agira provides two separate Django management commands for synchronizing data from GitHub:

## 1. GitHub Issue/PR Sync Worker

**Command:** `github_sync_worker`

**Purpose:** Synchronizes GitHub Issues and Pull Requests with Agira Items.

**Responsibilities:**
- Syncs status of GitHub Issues to Agira Items
- Updates Item status to "Testing" when GitHub Issue is closed
- Links Pull Requests to Issues based on timeline events
- Pushes Issue/PR content to Weaviate for AI indexing
- Respects the "Closed" status rule (items in Closed status are not synced)

**Usage:**
```bash
# Sync all projects
python manage.py github_sync_worker

# Sync specific project
python manage.py github_sync_worker --project-id 123

# Dry run (preview without making changes)
python manage.py github_sync_worker --dry-run

# Custom batch size
python manage.py github_sync_worker --batch-size 100
```

**Recommended Frequency:** Every 5-15 minutes (frequent updates needed for active development)

---

## 2. GitHub Markdown Sync Worker

**Command:** `github_markdown_sync_worker`

**Purpose:** Synchronizes markdown files from GitHub repositories to Agira project attachments.

**Responsibilities:**
- Finds all `.md` files in linked GitHub repositories
- Downloads markdown file content
- Creates/updates project attachments with the files
- Indexes file **content** (not just filename) in Weaviate for AI search
- Tracks file versions via GitHub SHA to avoid unnecessary downloads

**Usage:**
```bash
# Sync markdown files for all projects
python manage.py github_markdown_sync_worker

# Sync specific project
python manage.py github_markdown_sync_worker --project-id 123

# Dry run (preview without making changes)
python manage.py github_markdown_sync_worker --dry-run
```

**Recommended Frequency:** Every 1-6 hours (markdown files change less frequently)

---

## Why Two Separate Workers?

The markdown sync functionality was extracted from the main `github_sync_worker` into a separate command because:

1. **Different Update Frequencies**: Issue/PR sync needs to run frequently (minutes), while markdown files change less often (hours)
2. **Performance**: Markdown sync is slower (downloading files) and would unnecessarily slow down Issue/PR sync
3. **Resource Efficiency**: Avoids downloading files every time Issues are synced
4. **Independent Scaling**: Each worker can be scheduled and scaled independently

---

## Scheduling Examples

### Using Cron

```cron
# GitHub Issue/PR sync every 10 minutes
*/10 * * * * cd /path/to/agira && python manage.py github_sync_worker

# GitHub Markdown sync every 3 hours
0 */3 * * * cd /path/to/agira && python manage.py github_markdown_sync_worker
```

### Using Systemd Timers

Create two timer units:

**github-sync.timer** (frequent)
```ini
[Unit]
Description=GitHub Issue/PR Sync Timer

[Timer]
OnBootSec=5min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

**github-markdown-sync.timer** (less frequent)
```ini
[Unit]
Description=GitHub Markdown Sync Timer

[Timer]
OnBootSec=15min
OnUnitActiveSec=3h

[Install]
WantedBy=timers.target
```

---

## Weaviate Integration

Both workers integrate with Weaviate for AI-powered search:

- **github_sync_worker**: Indexes Issue/PR titles, bodies, and comments
- **github_markdown_sync_worker**: Indexes full markdown file **content** (not just filenames)

This allows AI agents to search through both Issues/PRs and documentation when answering questions.

---

## Common Configuration

Both workers require GitHub integration to be enabled and configured:

1. Go to Django Admin → GitHub Configuration
2. Enable GitHub integration
3. Set GitHub API token
4. Configure projects with `github_owner` and `github_repo` fields

---

## Troubleshooting

### Worker fails with "GitHub integration is not enabled"
- Enable GitHub in Django Admin → GitHub Configuration

### Worker fails with "GitHub integration is not configured"
- Set a valid GitHub token in Django Admin → GitHub Configuration

### Markdown files not syncing
- Verify project has `github_owner` and `github_repo` configured
- Check GitHub token has read permissions for the repository
- Run with `--dry-run` to see what would be synced

### No Items being synced
- Ensure ExternalIssueMapping records exist for your Items
- Check that Items are not in "Closed" status (these are intentionally skipped)
