# UI Screenshots and Visual Guide

## Move Item Feature - User Interface

### 1. Item Detail Page - Move Button

The Move button appears in the action bar at the top of the item detail page, between the Edit and Delete buttons:

```
┌─────────────────────────────────────────────────────────────────┐
│  Item Title                                                      │
│  Project Name • Item Type                                        │
│                                                                  │
│  [← Back to Project]  [Status Badge]  [Weaviate]               │
│  [✏ Edit]  [↔ Move]  [🗑 Delete]                               │
└─────────────────────────────────────────────────────────────────┘
```

Visual Characteristics:
- Button style: `btn btn-outline-secondary btn-sm`
- Icon: Left-right arrow (bi-arrow-left-right)
- Label: "Move"
- Position: Between Edit (primary) and Delete (danger) buttons

### 2. Move Item Modal

When the Move button is clicked, a Bootstrap modal appears:

```
┌──────────────────────────────────────────────────────────────────┐
│ ← → Item verschieben                                          ✕ │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ℹ  Beim Verschieben werden projektabhängige Felder (Nodes,     │
│     Parent-Item, Release) zurückgesetzt, wenn sie nicht zum      │
│     Zielprojekt passen.                                          │
│                                                                   │
│  Zielprojekt *                                                   │
│  [-- Projekt auswählen --          ▼]                           │
│  │  Project A                        │                          │
│  │  Project B                        │                          │
│  │  Project C                        │                          │
│  └──────────────────────────────────┘                           │
│                                                                   │
│  ☑ Mail an Requester senden                                     │
│                                                                   │
│  Note: Es wird keine Mail versendet, da das Item keinen         │
│  Requester mit E-Mail-Adresse hat. (if applicable)              │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│                                    [✕ Abbrechen] [✓ Verschieben] │
└──────────────────────────────────────────────────────────────────┘
```

Modal Elements:
- **Header**: Blue background (bg-primary) with white text
- **Info Alert**: Blue info box explaining field clearing behavior
- **Project Dropdown**: Required field (marked with *)
  - Lists all projects except the current one
  - Bootstrap form-select component
- **Email Checkbox**: Enabled by default
  - Shows warning if requester has no email
  - Disabled appearance if no email available
- **Error Display**: Hidden by default, shows in red if validation fails
- **Footer Buttons**:
  - Cancel: Secondary (gray)
  - Verschieben: Primary (blue) with checkmark icon

### 3. Loading State

During the move operation:

```
┌──────────────────────────────────────────────────────────────────┐
│                                    [✕ Abbrechen] [⟳ Verschiebe...] │
└──────────────────────────────────────────────────────────────────┘
```

- Confirm button disabled
- Spinner icon replaces checkmark
- Text changes to "Verschiebe..."

### 4. Success State

After successful move, a toast notification appears:

```
┌────────────────────────────────────────────────┐
│ ✓ Erfolg                                    ✕  │
│                                                 │
│ Item moved to Project B - E-Mail wurde        │
│ versendet.                                      │
└────────────────────────────────────────────────┘
```

Variations:
- **With email**: "Item moved to [Project] - E-Mail wurde versendet."
- **Without email**: "Item moved to [Project]"
- **Email failed**: "Item moved to [Project] - E-Mail konnte nicht versendet werden: [error]"

The page automatically reloads after 1 second to show the item in its new project.

### 5. Error State

If validation or server error occurs:

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                   │
│  ⚠ Bitte wählen Sie ein Zielprojekt aus.                        │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│                                    [✕ Abbrechen] [✓ Verschieben] │
└──────────────────────────────────────────────────────────────────┘
```

- Error message appears in red alert box
- Button returns to normal state
- User can correct and retry

Common error messages:
- "Bitte wählen Sie ein Zielprojekt aus." (No project selected)
- "Item is already in the target project" (Same project selected)
- "Fehler: [message]" (Server/network error)

## User Flow Diagram

```
┌──────────────┐
│ Item Detail  │
│    Page      │
└──────┬───────┘
       │
       │ Click "Move"
       │
       ▼
┌──────────────┐
│ Move Modal   │
│   Opens      │
└──────┬───────┘
       │
       │ Select Project
       │ (Optional: Toggle Email)
       │
       ▼
┌──────────────┐         ┌──────────────┐
│ Validation   ├────────►│ Show Error   │
│    Fails?    │   Yes   │  in Modal    │
└──────┬───────┘         └──────────────┘
       │ No
       │
       ▼
┌──────────────┐
│   Loading    │
│    State     │
└──────┬───────┘
       │
       ▼
┌──────────────┐         ┌──────────────┐
│   Server     ├────────►│ Show Error   │
│   Error?     │   Yes   │    Toast     │
└──────┬───────┘         └──────────────┘
       │ No
       │
       ▼
┌──────────────┐
│   Success    │
│    Toast     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Page Reload  │
│ (New Project)│
└──────────────┘
```

## Email Notification

When email is enabled, the requester receives:

```
From: Agira <[configured sender]>
To: [requester email]
CC: [follower emails]
Subject: [AGIRA-123] Item verschoben: [Item Title]

──────────────────────────────────────────────

Hallo,

das Item "[Item Title]" wurde in ein anderes Projekt verschoben.

Details:
• Neues Projekt: [Project Name]
• Status: [Status]
• Typ: [Type]
• Zugewiesen an: [Assignee]
• Release: [Release]

Beschreibung:
[Item Description]

Mit freundlichen Grüßen
Agira Team
```

Note: The [AGIRA-123] prefix is automatically added by the mail service for threading support.

## Responsive Design

The modal is responsive and works on mobile devices:
- Modal dialog uses `modal-lg` for larger screens
- Automatically adjusts to smaller screens
- Touch-friendly button sizes
- Dropdown works with mobile keyboards

## Accessibility

- Modal has proper ARIA labels
- Keyboard navigation supported (Tab, Enter, Esc)
- Required fields marked with asterisk
- Error messages associated with form fields
- Color contrast meets WCAG standards (blue primary, red errors)
- Screen reader friendly labels and alerts

## Browser Compatibility

Tested with modern browsers:
- Chrome/Edge (Chromium-based)
- Firefox
- Safari
- Mobile browsers (iOS Safari, Chrome Android)

Uses standard Bootstrap 5 components and ES6 JavaScript (fetch API).
