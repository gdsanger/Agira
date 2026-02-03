# Visual Guide: Solution Release Badge Feature

## Overview Diagram

```
Item Detail Page
┌──────────────────────────────────────────────────────────────┐
│                        ITEM DETAIL                            │
│                                                               │
│  [Main Content Area]                                          │
│                                                               │
│  ┌────────────────────────────────────────────────────┐      │
│  │ Additional Information    [Release: 1.2.0] ◄─────┐│      │
│  ├────────────────────────────────────────────────────┤      ││
│  │                                                    │      ││
│  │ Intern: ☐                                         │      ││
│  │                                                    │      ││
│  │ Status: Working                                   │      ││
│  │                                                    │      ││
│  │ Solution Release:                                 │      ││
│  │ ┌──────────────────────────────────┐              │      ││
│  │ │ [Select Release ▼]               │ ◄────────────┼─┐    ││
│  │ └──────────────────────────────────┘              │ │    ││
│  │                                                    │ │    ││
│  └────────────────────────────────────────────────────┘ │    ││
└──────────────────────────────────────────────────────────┼────┼┘
                                                          │    │
                                                          │    │
┌─────────────────────────────────────────────────────────┘    │
│ BADGE (in card header)                                       │
│ - Always shows current assignment                            │
│ - Green if Closed                                            │
│ - Blue if Planned/Working                                    │
│ - Shows even if not in dropdown                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ DROPDOWN (in card body)                                      │
│ - Only shows selectable releases                             │
│ - Filtered by project (server-side)                          │
│ - Excludes Closed status (server-side)                       │
└──────────────────────────────────────────────────────────────┘
```

## Color Coding Examples

### Scenario 1: Item with Working Release
```
┌─────────────────────────────────────────────┐
│ Additional Information    [Release: 1.2.0]  │ ← Blue badge
├─────────────────────────────────────────────┤    (bg-info)
│ Solution Release: [1.2.0 ▼]                 │ ← In dropdown
└─────────────────────────────────────────────┘
```

### Scenario 2: Item with Closed Release
```
┌─────────────────────────────────────────────┐
│ Additional Information    [Release: 1.0.0]  │ ← Green badge
├─────────────────────────────────────────────┤    (bg-success)
│ Solution Release: [None ▼]                  │ ← NOT in dropdown
│                   [1.1.0]                   │    (Closed excluded)
│                   [1.2.0]                   │
└─────────────────────────────────────────────┘
```

### Scenario 3: Item with No Release
```
┌─────────────────────────────────────────────┐
│ Additional Information                      │ ← No badge
├─────────────────────────────────────────────┤
│ Solution Release: [None ▼]                  │ ← Empty selection
│                   [1.1.0]                   │
│                   [1.2.0]                   │
└─────────────────────────────────────────────┘
```

## Data Flow

```
┌──────────────────┐
│   Database       │
│                  │
│  ┌────────────┐  │
│  │   Item     │  │
│  │            │  │
│  │ solution_  │  │
│  │ release_id │  │
│  └────┬───────┘  │
│       │          │
│       │          │
│  ┌────▼───────┐  │
│  │  Release   │  │
│  │            │  │
│  │ - version  │  │
│  │ - status   │  │
│  │ - project  │  │
│  └────────────┘  │
└──────┬───────────┘
       │
       │ select_related('solution_release')
       │
       ▼
┌──────────────────┐
│  Django View     │
│  (item_detail)   │
│                  │
│  Queries:        │
│  1. Load item    │◄────────┐
│     with release │         │
│                  │         │
│  2. Get dropdown │         │ Server-side
│     options:     │         │ filtering
│     - Same       │         │
│       project    │─────────┘
│     - Not Closed │
└────────┬─────────┘
         │
         │ context = {item, releases}
         │
         ▼
┌──────────────────┐
│   Template       │
│                  │
│  Badge:          │
│  if item.        │
│     solution_    │
│     release:     │
│    show badge    │
│                  │
│  Dropdown:       │
│  for release     │
│    in releases:  │
│    show option   │
└──────────────────┘
```

## Code Cross-Reference

### Template (templates/item_detail.html)
```html
Line 467-476: Badge implementation
  │
  ├─ Line 470: {% if item.solution_release %}
  │              ↓
  ├─ Line 471:   Conditional color (Closed → green, else → blue)
  │              ↓
  └─ Line 472:   Display version
  
Line 561-577: Dropdown implementation
  │
  ├─ Line 572: {% for release in releases %}
  │              ↓
  └─ Line 573:   Check if selected
```

### Backend (core/views.py)
```python
Line 765-803: item_detail view
  │
  ├─ Line 770: select_related('solution_release')
  │              ↓ (eager loading for badge)
  │
  └─ Line 785-789: Filter releases for dropdown
       ├─ project=item.project
       └─ exclude Closed
```

### Tests (core/test_item_detail.py)
```python
Line 675-900: SolutionReleaseFilteringTest class
  │
  ├─ test_releases_filtered_by_project
  ├─ test_releases_exclude_closed_status
  ├─ test_badge_shows_assigned_closed_release ◄── Badge tests
  ├─ test_badge_shows_assigned_foreign_project_release
  ├─ test_no_badge_when_no_release_assigned
  └─ test_empty_dropdown_when_all_releases_closed
```

## Bootstrap Classes Reference

| Class | Color | Purpose in Feature |
|-------|-------|-------------------|
| `bg-success` | Green | Closed releases (completed) |
| `bg-info` | Blue | Active releases (Planned/Working) |
| `badge` | - | Bootstrap badge styling |

## User Interaction Flow

1. User opens Item detail page
2. Django loads Item with `solution_release` via select_related()
3. Template checks if `item.solution_release` exists
   - **YES**: Show badge with version and color
   - **NO**: Don't show badge
4. Django queries selectable releases (filtered)
5. Template renders dropdown with filtered options
6. User can change selection (if needed)
   - Badge will update on next page load
   - Closed/foreign releases won't be re-selectable

## Edge Cases Handled

✅ Release is Closed → Badge shows (green), not in dropdown  
✅ Release from different project → Badge shows, not in dropdown  
✅ Release deleted → Badge hidden (solution_release is NULL)  
✅ No releases available → Dropdown empty, no badge  
✅ All releases Closed → Dropdown empty, badge may show (if assigned)
