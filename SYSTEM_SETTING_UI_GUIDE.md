# System Settings - Visual UI Guide

## Navigation Location

The System Settings page is accessible from the left sidebar under the **Configuration** section:

```
Sidebar Navigation
├── Dashboard
├── Projects
├── Items
├── ...
└── Configuration (expandable)
    ├── System Settings ← NEW
    ├── Global Settings
    ├── Issue Blueprints
    ├── Mail Templates
    ├── Mail Action Mappings
    └── Change Policies
```

## Page Layout

### Header Section
```
┌─────────────────────────────────────────────────────────────┐
│ Breadcrumb: Dashboard > System Settings                     │
│                                                              │
│ System Settings                                              │
│ Configure system-wide settings                               │
└─────────────────────────────────────────────────────────────┘
```

### Main Content (Left Column - 8/12 width)

#### Card 1: System Information Form
```
┌─────────────────────────────────────────────────────────────┐
│ System Information                                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ System Name *                                                │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ Agira Issue Tracking v1.0                              │  │
│ └────────────────────────────────────────────────────────┘  │
│ The name of the system                                       │
│                                                              │
│ Company *                                                    │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ Agira Software Enterprises                             │  │
│ └────────────────────────────────────────────────────────┘  │
│ The company name                                             │
│                                                              │
│ Email *                                                      │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ agira@angermeier.net                                   │  │
│ └────────────────────────────────────────────────────────┘  │
│ Company contact email address                                │
│                                                              │
│ Company Logo                                                 │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ [Current Logo Image Preview]                           │  │
│ │ Relative Path: system_settings/logo.png                │  │
│ └────────────────────────────────────────────────────────┘  │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ Choose File                                            │  │
│ └────────────────────────────────────────────────────────┘  │
│ Upload a logo (PNG, JPG, WEBP, GIF - max 5 MB).             │
│ The relative path will be stored for use in HTML/Weasyprint.│
│                                                              │
│                                   ┌──────────────────────┐  │
│                                   │ 💾 Save Settings     │  │
│                                   └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

#### Card 2: Metadata
```
┌─────────────────────────────────────────────────────────────┐
│ Metadata                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ Created        2026-02-10 20:57                              │
│ Last Updated   2026-02-10 21:15                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Sidebar (Right Column - 4/12 width)

#### Information Card
```
┌─────────────────────────────────────────────────────────────┐
│ ℹ️ Information                                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ About System Settings                                        │
│ These settings configure system-wide parameters for your    │
│ Agira installation. All fields are required except the logo.│
│                                                              │
│ Company Logo                                                 │
│ The company logo is stored with a relative path and can be  │
│ used in:                                                     │
│ • HTML templates                                             │
│ • PDF reports (Weasyprint)                                   │
│ • Email templates                                            │
│ • Public-facing pages                                        │
│                                                              │
│ Supported Formats                                            │
│ • PNG (recommended for logos)                                │
│ • JPEG/JPG                                                   │
│ • WEBP                                                       │
│ • GIF                                                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Interactive Features

### 1. HTMX-Based Updates
- Form submission via AJAX (no page reload)
- Success: Green toast notification appears in top-right corner
- Error: Red toast notification with error message
- Automatic page reload after successful update to show new values

### 2. File Upload
- Click "Choose File" to select logo
- Preview shows current logo if one exists
- Displays relative path below preview
- Old logo is automatically deleted when new one is uploaded

### 3. Validation
- Required fields marked with red asterisk (*)
- Email field validates format
- Image upload validates file type
- Error messages shown via toast notifications

## Toast Notifications

### Success Toast
```
┌─────────────────────────────────────────┐
│ Notification                         × │
├─────────────────────────────────────────┤
│ Settings updated successfully           │
└─────────────────────────────────────────┘
```
- Background: Green
- Duration: Auto-dismiss after 3 seconds
- Position: Top-right corner

### Error Toast
```
┌─────────────────────────────────────────┐
│ Notification                         × │
├─────────────────────────────────────────┤
│ Validation error: email: Invalid email  │
└─────────────────────────────────────────┘
```
- Background: Red
- Duration: Auto-dismiss after 5 seconds
- Position: Top-right corner

## Admin Interface

### List View
```
┌─────────────────────────────────────────────────────────────┐
│ Select system setting to change                             │
├─────────────────────────────────────────────────────────────┤
│ System Settings - Agira Issue Tracking v1.0                 │
└─────────────────────────────────────────────────────────────┘
```
- Shows single record (singleton)
- "Add" button disabled (singleton pattern)
- "Delete" option not available

### Edit View
```
┌─────────────────────────────────────────────────────────────┐
│ Change system setting                                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ System Name:   [Agira Issue Tracking v1.0]                  │
│ Company:       [Agira Software Enterprises]                 │
│ Email:         [agira@angermeier.net]                        │
│                                                              │
│ LOGO                                                         │
│ Company Logo:  [Browse...] Currently: system_settings/logo.png│
│                                                              │
│ METADATA (collapsed)                                         │
│ Created At:    2026-02-10 20:57                              │
│ Updated At:    2026-02-10 21:15                              │
│                                                              │
│ [Save and continue editing] [Save]                           │
└─────────────────────────────────────────────────────────────┘
```

## Responsive Design

### Desktop (≥992px)
- Two-column layout (8/4 split)
- Form on left, information on right
- Full navigation sidebar visible

### Tablet (768px - 991px)
- Two-column layout (stacked on smaller tablets)
- Navigation sidebar collapsible
- Form fields full width

### Mobile (<768px)
- Single column layout
- Sidebar hidden by default
- Form fields full width
- Toast notifications adjust to screen size

## Color Scheme (Bootstrap 5)

- **Primary**: Blue (#0d6efd) - Save button
- **Success**: Green (#198754) - Success toast
- **Danger**: Red (#dc3545) - Error toast
- **Info**: Light blue (#0dcaf0) - Info sections
- **Secondary**: Gray (#6c757d) - Secondary text
- **Light**: Light gray (#f8f9fa) - Card backgrounds

## Icons (Bootstrap Icons)

- **System Settings**: `bi-sliders` - Navigation icon
- **Save**: `bi-save` - Save button
- **Info**: `bi-info-circle` - Information sections
- **Breadcrumb**: Standard breadcrumb separators

## Accessibility

- Proper form labels with `for` attributes
- Required fields marked with asterisk and `required` attribute
- ARIA labels for screen readers
- Color contrast meets WCAG AA standards
- Keyboard navigation supported
- Toast notifications with proper ARIA roles
