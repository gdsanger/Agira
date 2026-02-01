# Visual Guide: Change Associated Items Feature

## Before and After

### BEFORE
```
Change Detail View - "Associated Items" section:
┌────────────────────────────────────────┐
│ Associated Items                       │
├────────────────────────────────────────┤
│ • Item Title 1 [Type]                 │
│ • Item Title 2 [Type]                 │
└────────────────────────────────────────┘

Source: change.items.all() (only M2M items)
```

### AFTER
```
Change Detail View - "Associated Items" section:
┌────────────────────────────────────────────────────────┐
│ Associated Items                                        │
├──────────┬────────────┬──────────────────────────────┤
│ Item ID  │ Type       │ Title                        │
├──────────┼────────────┼──────────────────────────────┤
│ #123     │ [Feature]  │ Item Title 1                 │
│ #124     │ [Bug]      │ Item Title 2                 │
│ #125     │ [Feature]  │ Release Item 1               │
│ #126     │ [Feature]  │ Release Item 2               │
└──────────┴────────────┴──────────────────────────────┘

Source: change.get_associated_items() 
        (M2M items + Release items, deduplicated)
```

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          Change Model                            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ get_associated_items()                                    │  │
│  │                                                            │  │
│  │  1. Get direct M2M items:                                 │  │
│  │     ├─> change.items.all()                                │  │
│  │                                                            │  │
│  │  2. If change.release_id is not None:                     │  │
│  │     ├─> Item.objects.filter(solution_release=release)     │  │
│  │                                                            │  │
│  │  3. Deduplicate by ID using set()                         │  │
│  │                                                            │  │
│  │  4. Return QuerySet ordered by ID                         │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ (same method used by both)
                            │
          ┌─────────────────┴──────────────────┐
          │                                     │
          ▼                                     ▼
┌──────────────────────┐          ┌─────────────────────────┐
│   Change Detail      │          │   Change PDF Report     │
│   View (UI)          │          │                         │
│                      │          │                         │
│  • Table display     │          │  • Items section        │
│  • Item ID column    │          │  • Table with 3 cols    │
│  • Type column       │          │  • Item ID, Type, Title │
│  • Title column      │          │                         │
└──────────────────────┘          └─────────────────────────┘
```

## Example Scenario

### Setup
```
Project: "Web Application"
├── Release: v1.0
│   ├── Item #101: "Add login feature" (Type: Feature)
│   ├── Item #102: "Fix CSS bug" (Type: Bug)
│   └── Item #103: "Update documentation" (Type: Task)
│
└── Change: "Deploy v1.0 to Production"
    ├── release: v1.0
    └── items (M2M): [Item #104: "Backup database"]
```

### Result in UI/PDF

The "Associated Items" section will show:

| Item ID | Type    | Title                   | Source          |
|---------|---------|-------------------------|-----------------|
| #101    | Feature | Add login feature       | From Release    |
| #102    | Bug     | Fix CSS bug             | From Release    |
| #103    | Task    | Update documentation    | From Release    |
| #104    | Task    | Backup database         | Direct M2M      |

**All 4 items displayed, ordered by ID**

### Deduplication Example

If Item #101 was also added directly to the Change via M2M:
```
Change.items.add(item_101)  # Already in release
```

Result: **Still only 4 items** (Item #101 appears once, not twice)

## Testing Coverage

```
┌─────────────────────────────────────────────────────────┐
│ Test Suite: ChangeAssociatedItemsTestCase               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ ✓ test_get_associated_items_with_release               │
│   → Verifies release items are included                 │
│                                                          │
│ ✓ test_get_associated_items_without_release            │
│   → Verifies empty result when no release               │
│                                                          │
│ ✓ test_get_associated_items_with_direct_items          │
│   → Verifies both sources combined                      │
│                                                          │
│ ✓ test_get_associated_items_deduplication              │
│   → Verifies no duplicates                              │
│                                                          │
│ ✓ test_get_associated_items_ordering                   │
│   → Verifies stable ordering by ID                      │
│                                                          │
│ ✓ test_change_detail_view_with_release_items           │
│   → Verifies view integration                           │
│                                                          │
│ ✓ test_pdf_includes_release_items                      │
│   → Verifies PDF generation                             │
│                                                          │
│ ✓ test_pdf_without_items                               │
│   → Verifies edge case handling                         │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## PDF Report Structure

```
┌──────────────────────────────────────────────────────┐
│ Change Report                                         │
│ Change ID: 123                                        │
│ Generated: 2026-02-01 15:30:00                       │
├──────────────────────────────────────────────────────┤
│                                                       │
│ 1. Change Overview                                   │
│ 2. Description & Justification                       │
│ 3. Implementation & Planning                         │
│ 4. Risk Assessment                                   │
│ 5. Approvals & Review                                │
│                                                       │
│ 6. Items                          ← NEW SECTION      │
│    ┌────────┬─────────┬──────────────────────┐      │
│    │ Item ID│ Type    │ Title                │      │
│    ├────────┼─────────┼──────────────────────┤      │
│    │ 101    │ Feature │ Add login feature    │      │
│    │ 102    │ Bug     │ Fix CSS bug          │      │
│    │ 103    │ Task    │ Update documentation │      │
│    └────────┴─────────┴──────────────────────┘      │
│                                                       │
│ 7. Organisations                                     │
│ 8. Attachments & References                          │
│                                                       │
└──────────────────────────────────────────────────────┘
```

## Benefits

1. **Completeness**: All relevant items are shown (Release + Direct)
2. **Consistency**: UI and PDF show identical data
3. **Efficiency**: Single query with proper optimization
4. **Clarity**: Table format makes information easy to scan
5. **Reliability**: Deduplication prevents confusion
6. **Traceability**: Item ID provides quick reference
