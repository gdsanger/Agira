# Recents & Pinned Sidebar - Visual Guide

## Overview
The Recents & Pinned feature adds a productivity-focused section to Agira's sidebar, similar to Zammad's interface.

## Feature Location
The feature appears at the bottom of the left sidebar, below all navigation links.

```
┌─────────────────────────┐
│ Agira                   │  ← Topbar
├─────────────────────────┤
│ Dashboard               │
│ Projects                │  
│ New Item                │
│ Items ▼                 │  ← Regular Navigation
│   Inbox                 │
│   Backlog               │
│   Working               │
│   ...                   │
│ Changes                 │
│ ...                     │
├─────────────────────────┤
│ GEPINNT            3/5  │  ← Pinned Section
│ #353 UI: Sidebar...  📌❌│
│ #249 PDF Template... 📌❌│
│ Projekt: Agira       📌❌│
├─────────────────────────┤
│ ZULETZT GEÖFFNET  5/20  │  ← Recents Section
│ #342 Markdown Fix    📍❌│
│ #338 Azure AD SSO    📍❌│
│ Projekt: Domus       📍❌│
│ #301 Email Ingest... 📍❌│
│ #289 Attachment...   📍❌│
│ [Alle löschen]          │
└─────────────────────────┘
```

## Visual Elements

### Section Headers
```
GEPINNT                3/5
├─ Title: "GEPINNT" (uppercase, muted)
└─ Counter: Current/Max items
```

### Entry Display
```
┌────────────────────────────────┐
│ 🔘 #249 PDF Template Generation │ ← Icon + Title
│    Issue • Testing              │ ← Type • Status
│                          📌 ❌  │ ← Actions (on hover)
└────────────────────────────────┘
```

### Icons Legend
- 🔘 = Issue icon (bi-exclamation-circle)
- 📁 = Project icon (bi-folder)
- 📍 = Pin button (bi-pin)
- 📌 = Unpin button (bi-pin-fill, yellow)
- ❌ = Remove button (bi-x-circle, red)

## Color Scheme (Dark Theme)

### Background Colors
- Sidebar: `#121720` (--bg-secondary)
- Entry hover: `#1a2030` (--bg-tertiary)
- Active entry: `rgba(99, 102, 241, 0.12)` (accent with opacity)

### Text Colors
- Section title: `#64748b` (--text-muted)
- Entry title: `#cbd5e1` (--text-secondary)
- Entry type/status: `#64748b` (--text-muted)
- Active entry: `#6366f1` (--accent-primary)

### Accent Colors
- Border (active): `#6366f1` (--accent-primary)
- Pin icon: `#eab308` (yellow/warning)
- Remove icon: `#ef4444` (red/danger)

## Interactive States

### Default State
```
Entry: No background, muted text
Actions: Hidden (opacity: 0)
Border: Transparent
```

### Hover State
```
Entry: Tertiary background, primary text
Actions: Visible (opacity: 1)
Border: Left border in accent color (3px)
Cursor: Pointer
```

### Active State (Current Page)
```
Entry: Accent background with opacity
Text: Accent color
Border: Left border in accent color (3px)
Font: Medium weight
```

## Responsive Behavior

### Desktop (≥768px / md+)
```
Sidebar visible with recents section
Full navigation + Recents & Pinned
Width: 260px
```

### Mobile (<768px)
```
Recents section hidden (d-none d-md-block)
Only regular navigation shown
Sidebar collapsible
```

### Collapsed Sidebar
```
When sidebar is collapsed:
- Recents section completely hidden
- Only icons shown for regular navigation
- Width: 70px
```

## Typography

### Section Headers
```
Font size: 0.75rem
Font weight: 600
Text transform: UPPERCASE
Letter spacing: 0.05em
Color: var(--text-muted)
```

### Entry Title
```
Font size: 0.875rem
Font weight: 500
White space: nowrap
Overflow: hidden
Text overflow: ellipsis
```

### Entry Meta (Type/Status)
```
Font size: 0.7rem
Color: var(--text-muted)
Display: Inline with separator (•)
```

## Spacing & Layout

### Section
```
Padding: 1rem 0
Border-top: 1px solid var(--border-color)
Margin-bottom: 1rem
```

### Section Header
```
Padding: 0.5rem 1.25rem
Display: flex
Justify: space-between
```

### Entry
```
Padding: 0.75rem 1.25rem
Display: flex
Gap: 0.5rem
Border-left: 3px solid transparent
```

### Actions
```
Display: flex
Gap: 0.25rem
Opacity: 0 (visible on hover)
Transition: opacity 0.2s ease
```

## Animation & Transitions

### Entry Hover
```css
transition: all 0.2s ease
```

### Action Buttons Appearance
```css
opacity: 0 → 1
transition: opacity 0.2s ease
```

### Border Highlight
```css
border-left-color: transparent → accent
transition: all 0.2s ease
```

## User Interactions

### 1. Viewing Recent Items
```
User visits: /items/249/
→ JavaScript detects touch marker
→ Item added to recents (or moved to top if exists)
→ localStorage updated
→ Sidebar re-rendered
→ User sees #249 at top of "Zuletzt geöffnet"
```

### 2. Pinning an Item
```
User hovers over recent item
→ Actions buttons appear
→ User clicks pin icon (📍)
→ Item removed from recents
→ Item added to pinned
→ Limit checked (max 5)
→ Toast notification shown
→ Sidebar re-rendered
→ Item now in "Gepinnt" section
```

### 3. Unpinning an Item
```
User hovers over pinned item
→ Actions buttons appear  
→ User clicks filled pin icon (📌)
→ Item removed from pinned
→ Item added back to recents (top)
→ Toast notification shown
→ Sidebar re-rendered
→ Item now in "Zuletzt geöffnet" section
```

### 4. Removing an Item
```
User hovers over any item
→ Actions buttons appear
→ User clicks X icon (❌)
→ Item removed from current list
→ localStorage updated
→ Sidebar re-rendered
→ Item no longer visible
```

### 5. Clearing All Recents
```
User clicks "Alle löschen"
→ Confirmation dialog appears
→ User confirms
→ All recents cleared (pinned preserved)
→ Toast notification shown
→ Sidebar re-rendered
→ Only pinned items remain
```

## Edge Cases Handled

### Maximum Limits
```
Pinned: 5 items
→ Attempt to pin 6th item
→ Toast warning shown
→ Action prevented

Recents: 20 items
→ 21st item visited
→ Oldest item removed
→ New item added at top
```

### Invalid Data
```
Missing or invalid ID
→ Validation check fails
→ Console error logged
→ Action prevented
→ No localStorage corruption
```

### Pinned Item Visited
```
User visits pinned item
→ Touch detected
→ Item already in pinned
→ Item NOT added to recents
→ No duplicate in lists
```

## Toast Notifications

### Pin Success
```
Type: success (green)
Message: "Item wurde angepinnt."
```

### Unpin Success
```
Type: success (green)
Message: "Item wurde entpinnt."
```

### Pin Limit Reached
```
Type: warning (yellow)
Message: "Maximal 5 Items können angepinnt werden."
```

### Clear Success
```
Type: success (green)
Message: "Zuletzt geöffnete Items wurden gelöscht."
```

### Already Pinned
```
Type: info (blue)
Message: "Item ist bereits angepinnt."
```

## Accessibility

### Screen Readers
```
Buttons have title attributes:
- "Anpinnen" (Pin)
- "Entpinnen" (Unpin)
- "Entfernen" (Remove)

Links are properly labeled with full text
```

### Keyboard Navigation
```
All buttons and links are focusable
Tab order: Top to bottom
Enter/Space activates actions
```

### Visual Indicators
```
Clear hover states
Focus indicators
Color contrast meets WCAG standards
Icons supplemented with text
```

## Performance

### localStorage Operations
```
Read: On page load (1x)
Write: Only on user action or page visit
Size: ~200 bytes per entry
Max total: ~20KB (100 entries @ 200 bytes)
```

### Rendering
```
Dynamic rendering via innerHTML
Event delegation (1 listener for all)
No re-binding required
Minimal DOM manipulation
```

### Memory
```
Small in-memory state (2 arrays)
No polling or intervals
No network requests
Pure client-side operation
```
