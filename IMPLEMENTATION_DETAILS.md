# Solution Release Badge - Implementation Details

## Overview

This document provides detailed information about the Solution Release Badge feature implementation in the Item Detail View.

## Feature Description

When viewing an Item's detail page, a badge appears in the "Additional Information" card header showing the currently assigned Solution Release. This badge provides quick visibility of the release assignment, even for releases that are:
- Closed (and thus not selectable in the dropdown)
- From a different project (legacy data scenario)

## Visual Implementation

### Location
The badge appears in the card header of the "Additional Information" section, aligned to the right side.

### HTML Structure
```html
<div class="card-header">
    <div class="d-flex justify-content-between align-items-center">
        <h5 class="mb-0">Additional Information</h5>
        {% if item.solution_release %}
            <span class="badge {% if item.solution_release.status == 'Closed' %}bg-success{% else %}bg-info{% endif %}">
                Release: {{ item.solution_release.version }}
            </span>
        {% endif %}
    </div>
</div>
```

### Color Scheme (Bootstrap 5)

| Release Status | Badge Color | Bootstrap Class | Purpose |
|---------------|-------------|-----------------|---------|
| Closed | Green | `bg-success` | Indicates successful completion |
| Planned | Blue | `bg-info` | Indicates active/future status |
| Working | Blue | `bg-info` | Indicates active/future status |
| None/Deleted | No badge | N/A | Hidden when release is null |

## Backend Implementation

### View: item_detail (core/views.py)

```python
def item_detail(request, item_id):
    """Item detail page with tabs."""
    item = get_object_or_404(
        Item.objects.select_related(
            'project', 'type', 'organisation', 'requester', 
            'assigned_to', 'solution_release'  # ← Eager loading
        ).prefetch_related('nodes'),
        id=item_id
    )
    
    # Get releases for the inline edit (filtered by project and exclude Closed)
    releases = Release.objects.filter(
        project=item.project           # ← Project filter
    ).exclude(
        status=ReleaseStatus.CLOSED    # ← Status filter
    ).order_by('-version')
```

### Key Points

1. **Eager Loading**: The `solution_release` is loaded via `select_related()` to avoid N+1 queries
2. **Dropdown Filtering**: Only shows releases from the same project with non-Closed status
3. **Badge vs Dropdown**: The badge shows ANY assigned release (even Closed/foreign), while dropdown only shows selectable options

## User Experience

### Scenario 1: Item with Active Release
- Badge shows: "Release: 1.2.0" (blue)
- Dropdown includes this release as an option

### Scenario 2: Item with Closed Release
- Badge shows: "Release: 1.0.0" (green)
- Dropdown DOES NOT include this release (correct - prevents re-selection)

### Scenario 3: Item with Foreign Project Release (Legacy Data)
- Badge shows: "Release: 2.0.0" (blue/green depending on status)
- Dropdown DOES NOT include this release (correct - wrong project)

### Scenario 4: Item with No Release
- No badge shown
- Dropdown shows available releases or "None"

## Database Schema

```python
class Item(models.Model):
    # ... other fields ...
    solution_release = models.ForeignKey(
        Release, 
        on_delete=models.SET_NULL,  # ← Auto-nulls if release deleted
        null=True, 
        blank=True, 
        related_name='items'
    )
```

## Test Coverage

Located in `core/test_item_detail.py`, class `SolutionReleaseFilteringTest`:

1. **test_releases_filtered_by_project**: Verifies dropdown only shows same-project releases
2. **test_releases_exclude_closed_status**: Verifies dropdown excludes Closed releases
3. **test_badge_shows_assigned_closed_release**: Badge visible for Closed release
4. **test_badge_shows_assigned_foreign_project_release**: Badge visible for foreign release
5. **test_no_badge_when_no_release_assigned**: No badge when release is None
6. **test_empty_dropdown_when_all_releases_closed**: Empty dropdown when only Closed releases exist

## Acceptance Criteria Checklist

✅ Badge in "Additional Information" card header  
✅ Shows release.version  
✅ Visible for Closed releases  
✅ Visible for foreign project releases  
✅ Color-coded (Closed=green, others=blue)  
✅ Display-only (not interactive)  
✅ Dropdown filters by project  
✅ Dropdown excludes Closed  
✅ Server-side filtering (not client-side)  
✅ Comprehensive test coverage  

## Files Modified (PR #365)

- `templates/item_detail.html`: Added badge to card header
- `core/views.py`: Added release filtering logic
- `core/test_item_detail.py`: Added comprehensive test suite

## References

- Issue: gdsanger/Agira#364
- PR: gdsanger/Agira#365
- Commit: aa54f3b
