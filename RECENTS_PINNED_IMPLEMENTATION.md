# Recents & Pinned Sidebar Feature - Implementation Summary

## Overview
This feature adds a "Recents & Pinned" section to the left sidebar, similar to Zammad's workspace feature. It allows users to:
- Track recently viewed items (Issues and Projects)
- Pin favorite items for quick access
- All data stored in browser's localStorage (no server-side storage)

## Files Created/Modified

### Created Files
1. **static/js/sidebar-recents.js** - JavaScript module for managing recents & pinned
2. **templates/partials/sidebar_recents.html** - Template partial for the sidebar UI

### Modified Files
1. **templates/base.html** - Added sidebar partial include and JavaScript import
2. **static/css/site.css** - Added CSS styles for recents/pinned section
3. **templates/item_detail.html** - Added touch tracking marker
4. **templates/project_detail.html** - Added touch tracking marker

## Features Implemented

### 1. LocalStorage Management
- **Keys**: `agira.sidebar.recents.v1` and `agira.sidebar.pinned.v1`
- **Limits**: Max 20 recents, max 5 pinned
- **Data Structure**:
```json
{
  "type": "issue|project",
  "id": 249,
  "title": "#249 PDF Template",
  "status": "in_progress",
  "url": "/items/249/",
  "ts": "2026-02-09T08:00:00Z"
}
```

### 2. UI Components
- **Pinned Section**: Shows up to 5 pinned items at the top
- **Recents Section**: Shows up to 20 recently viewed items
- **Empty State**: Shows message when no items exist
- **Responsive**: Only visible on medium+ screens (d-none d-md-block)

### 3. User Actions
- **Pin**: Click pin icon to pin an item (moves from recents to pinned)
- **Unpin**: Click filled pin icon to unpin (moves back to recents)
- **Remove**: Click X icon to remove from list
- **Clear All**: Button to clear all recents (with confirmation)
- **Active Highlighting**: Current page is highlighted in the list

### 4. Auto-Tracking
- Issue detail pages automatically add themselves to recents
- Project detail pages automatically add themselves to recents
- Pinned items are not re-added to recents when visited

### 5. User Feedback
- Toast notifications for pin/unpin actions
- Toast notification when pin limit is reached
- Confirmation dialog for clearing all recents

## CSS Styling
- Consistent with existing Agira dark theme
- Hover effects on entries
- Action buttons (pin/unpin/remove) appear on hover
- Active page highlighting with accent color
- Responsive design matching sidebar behavior

## Testing Checklist

### Manual Testing Steps
1. **Basic Navigation**
   - [ ] Visit an issue detail page
   - [ ] Verify issue appears in "Zuletzt geöffnet" section
   - [ ] Visit another issue
   - [ ] Verify both issues appear in recents
   - [ ] Visit a project detail page
   - [ ] Verify project appears in recents

2. **Pinning**
   - [ ] Hover over a recent item
   - [ ] Click the pin icon
   - [ ] Verify item moves to "Gepinnt" section
   - [ ] Verify toast notification appears
   - [ ] Pin 4 more items
   - [ ] Try to pin a 6th item
   - [ ] Verify limit warning appears

3. **Unpinning**
   - [ ] Hover over a pinned item
   - [ ] Click the filled pin icon
   - [ ] Verify item moves back to recents
   - [ ] Verify toast notification appears

4. **Removing**
   - [ ] Hover over a recent item
   - [ ] Click the X icon
   - [ ] Verify item is removed
   - [ ] Hover over a pinned item
   - [ ] Click the X icon
   - [ ] Verify item is removed

5. **Clear All**
   - [ ] Click "Alle löschen" button
   - [ ] Verify confirmation dialog appears
   - [ ] Confirm deletion
   - [ ] Verify all recents are cleared
   - [ ] Verify pinned items remain

6. **Navigation**
   - [ ] Click on a recent item
   - [ ] Verify navigation to correct page
   - [ ] Verify clicked item is highlighted as active

7. **Persistence**
   - [ ] Add some items to recents and pinned
   - [ ] Refresh the page
   - [ ] Verify items persist
   - [ ] Open a new browser tab to same site
   - [ ] Verify items appear in new tab

8. **Responsive Behavior**
   - [ ] View on desktop (>= md breakpoint)
   - [ ] Verify section is visible
   - [ ] Resize browser to mobile size (< md breakpoint)
   - [ ] Verify section is hidden
   - [ ] Resize back to desktop
   - [ ] Verify section appears again

9. **Sidebar Collapse**
   - [ ] Click sidebar toggle button
   - [ ] Verify recents section is hidden when collapsed
   - [ ] Click toggle again to expand
   - [ ] Verify recents section reappears

10. **Limits**
    - [ ] Add 21+ items to recents (by visiting pages)
    - [ ] Verify only 20 most recent items are shown
    - [ ] Verify oldest item is removed when adding 21st

## Technical Details

### Entry Shape
Each entry in localStorage follows this structure:
```javascript
{
  type: "issue" | "project",
  id: number,
  title: string,
  status: string,
  url: string,
  ts: ISO8601 timestamp
}
```

### Touch Mechanism
Detail pages include a hidden div with data attributes:
```html
<div style="display: none;" 
     data-recent-touch="1" 
     data-recent-type="issue|project" 
     data-recent-id="249" 
     data-recent-title="#249 PDF Template" 
     data-recent-status="in_progress" 
     data-recent-url="/items/249/"></div>
```

The JavaScript reads these attributes on page load and updates localStorage accordingly.

### Event Delegation
All click handlers use event delegation on the document, allowing for dynamic content updates without re-binding events.

### Public API
The module exposes a global `window.AgiraSidebarRecents` object with methods:
- `touchRecent(entry)`
- `pinItem(entry)`
- `unpinItem(entry)`
- `clearRecents()`

## Browser Compatibility
- Requires modern browser with localStorage support
- Requires ES6+ JavaScript support
- Bootstrap 5.3 compatibility
- Tested with Chrome, Firefox, Safari, Edge

## Known Limitations
1. Data is stored per-browser (not synced across devices)
2. Clearing browser data will clear recents/pinned
3. Only Issues and Projects are tracked (can be extended later)
4. No server-side backup of user preferences

## Future Enhancements (Out of Scope)
- Add support for more entity types (Customers, Sales Documents, etc.)
- Server-side storage for cross-device sync
- Customizable limits per user
- Drag-and-drop reordering
- Search/filter within recents
- Export/import functionality
