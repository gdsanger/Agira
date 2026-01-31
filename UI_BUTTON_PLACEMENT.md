# UI Button Placement

## Change Detail Page Header

```
┌────────────────────────────────────────────────────────────────────┐
│  Change Detail                                                     │
│                                                                    │
│  Database Migration                           [🖨 Drucken] [✏ Edit] [🗑 Delete]
│  Project: Test Project | Release: v1.0.0 (Major)                  │
└────────────────────────────────────────────────────────────────────┘
```

## Button Details

### "Drucken" (Print) Button
- **Position**: First button in action button group (left-most)
- **Style**: Bootstrap secondary button (gray)
- **Icon**: Bootstrap printer icon (`bi-printer`)
- **Action**: Opens PDF in new browser tab
- **URL**: `/changes/<id>/print/`
- **Target**: `_blank` (new tab/window)

### Button Order (Left to Right)
1. **Drucken** (Print) - Gray/Secondary - Printer icon
2. **Edit** - Blue/Primary - Pencil icon
3. **Delete** - Red/Danger - Trash icon

## User Workflow

```
User on Change Detail Page
        ↓
Clicks "Drucken" button
        ↓
New browser tab opens
        ↓
PDF loads inline in browser
        ↓
User can:
  - View the PDF
  - Download it
  - Print it
  - Close the tab
```

## PDF Preview in Browser

When the "Drucken" button is clicked, the browser opens a new tab showing the PDF:

```
┌─────────────────────────────────────────────────────────────────┐
│ 📄 change_1.pdf                                    [💾] [🖨] [×] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│    Change Report                                                │
│                                                                 │
│    Change ID: 1                                                 │
│    Report Generated: 2024-01-31 22:40:15                       │
│                                                                 │
│    Change Overview                                              │
│    ┌────────────────────────────────────────────────────┐     │
│    │ Field          │ Value                             │     │
│    ├────────────────────────────────────────────────────┤     │
│    │ Title          │ Database Migration                │     │
│    │ Project        │ Test Project                      │     │
│    │ Status         │ Planned                           │     │
│    │ Risk Level     │ High                              │     │
│    │ ...            │ ...                               │     │
│    └────────────────────────────────────────────────────┘     │
│                                                                 │
│    Description & Justification                                 │
│    Description:                                                │
│    Migrate database from MySQL to PostgreSQL                   │
│    This is a critical change.                                  │
│                                                                 │
│    [... more sections ...]                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Technical Details

### HTTP Response
```
HTTP/1.1 200 OK
Content-Type: application/pdf
Content-Disposition: inline; filename="change_1.pdf"
Content-Length: 4229

%PDF-1.4
...
```

### Browser Behavior
- **Chrome/Edge**: Shows PDF in built-in viewer
- **Firefox**: Shows PDF in built-in viewer
- **Safari**: Shows PDF in built-in viewer
- All browsers provide download and print options
