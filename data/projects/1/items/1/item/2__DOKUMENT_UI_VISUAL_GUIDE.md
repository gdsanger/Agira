# Document UI Visual Guide

## Overview
This guide describes the visual elements of the document management UI implemented for the Vermietung module.

## 1. Document Table (All Entity Detail Pages)

### Location
Each entity detail page (Vertrag, MietObjekt, Übergabeprotokoll, Adresse) has a documents section.

### Visual Elements

```
┌─────────────────────────────────────────────────────────────────┐
│  📄 Dokumente                                                    │
│                                                                  │
│  Dokumente für diese(n/s) [Entity]    [🔼 Dokument hochladen]  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Dateiname │ Größe │ Hochgeladen │ Von │ Aktionen         │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ 📄 contract.pdf                                          │  │
│  │ Vertragsdokument                                         │  │
│  │           2.3 MB  01.12.2024    admin  [⬇] [🗑]         │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ 📄 floor_plan.jpg                                        │  │
│  │ Grundriss                                                │  │
│  │           1.5 MB  15.11.2024    user1  [⬇] [🗑]         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  [← Zurück] Seite 1 von 1 [Weiter →]                           │
└─────────────────────────────────────────────────────────────────┘

Legend:
[🔼] = Upload button (opens modal)
[⬇] = Download button
[🗑] = Delete button (with confirmation)
```

### Empty State
```
┌─────────────────────────────────────────────────────────────────┐
│  📄 Dokumente                                                    │
│                                                                  │
│  Dokumente für diese(n/s) [Entity]    [🔼 Dokument hochladen]  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │              📭 Keine Dokumente vorhanden                 │  │
│  │                                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Upload Modal

### Triggered by
Clicking the "🔼 Dokument hochladen" button

### Visual Layout
```
┌─────────────────────────────────────────────────────────┐
│  🔼 Dokument hochladen                           ✕      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Datei *                                                 │
│  ┌────────────────────────────────────────────────┐     │
│  │ [Datei auswählen...]                           │     │
│  └────────────────────────────────────────────────┘     │
│  ℹ Erlaubte Dateitypen: PDF, PNG, JPG/JPEG, GIF, DOCX  │
│     Maximale Größe: 10 MB                               │
│                                                          │
│  Beschreibung (optional)                                │
│  ┌────────────────────────────────────────────────┐     │
│  │ Optional: Beschreibung des Dokuments           │     │
│  │                                                 │     │
│  │                                                 │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                         [Abbrechen] [🔼 Hochladen]      │
└─────────────────────────────────────────────────────────┘
```

### Behavior
1. Click "Datei auswählen..." to open file picker
2. File picker filters to allowed types (.pdf, .png, .jpg, .jpeg, .gif, .docx)
3. Optional: Enter description
4. Click "Hochladen" to upload
5. Modal closes automatically on success
6. Success/error message appears at top of page

## 3. Delete Confirmation Dialog

### Triggered by
Clicking the delete button (🗑) next to any document

### Visual Layout
```
┌─────────────────────────────────────────────────────────┐
│                                                          │
│  ⚠️  Bestätigung erforderlich                           │
│                                                          │
│  Möchten Sie das Dokument "contract.pdf" wirklich       │
│  löschen?                                                │
│                                                          │
│  Dieser Vorgang kann nicht rückgängig gemacht werden.   │
│                                                          │
│                         [Abbrechen] [OK]                 │
└─────────────────────────────────────────────────────────┘
```

### Behavior
1. User clicks delete button
2. Browser confirmation dialog appears
3. If confirmed: Document deleted, success message shown
4. If cancelled: Nothing happens, stays on page

## 4. Success/Error Messages

### Success Messages
```
┌─────────────────────────────────────────────────────────┐
│  ✅ Dokument "contract.pdf" wurde erfolgreich          │
│     hochgeladen.                                    [×] │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ✅ Dokument "contract.pdf" wurde erfolgreich          │
│     gelöscht.                                       [×] │
└─────────────────────────────────────────────────────────┘
```

### Error Messages
```
┌─────────────────────────────────────────────────────────┐
│  ❌ Fehler beim Hochladen: Die Dateigröße (15.5 MB)   │
│     überschreitet das Maximum von 10 MB.           [×] │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ❌ Fehler beim Hochladen: Dateityp "application/zip" │
│     ist nicht erlaubt. Erlaubte Typen: .pdf, .png,     │
│     .jpg, .jpeg, .gif, .docx                       [×] │
└─────────────────────────────────────────────────────────┘
```

## 5. Integration with Entity Detail Pages

### Vertrag (Contract) Detail Page
```
┌─────────────────────────────────────────────────────────┐
│  Vertrag: V-00001                                        │
│  [✏️ Bearbeiten] [📅 Beenden] [❌ Stornieren] [← Zurück] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  [Vertragsdaten Card]                                   │
│  [Mietobjekt Card]                                      │
│  [Mieter Card]                                          │
│  [Zeitraum Card]                                        │
│  [Finanzielle Konditionen Card]                         │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │ [📋 Übergabeprotokolle] [📄 Dokumente]          │   │
│  ├─────────────────────────────────────────────────┤   │
│  │                                                  │   │
│  │  [Document table as shown above]                │   │
│  │                                                  │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### MietObjekt (Rental Object) Detail Page
```
Similar layout with tabs for:
- Verträge (Contracts)
- Übergaben (Handover Protocols)
- Dokumente (Documents) ← New upload/delete functionality
```

### Übergabeprotokoll (Handover Protocol) Detail Page
```
Documents section at bottom of page with:
- Upload button
- Document table
- Download/delete actions
```

### Adresse/Kunde (Address/Customer) Detail Page
```
New documents section added below contact information with:
- Upload button
- Document table
- Download/delete actions
```

## 6. Responsive Design

### Desktop View (>768px)
- Full width table with all columns
- Modal centered on screen
- Action buttons side by side

### Tablet View (768px - 1024px)
- Condensed table (some columns may wrap)
- Modal takes more screen space
- Action buttons still visible

### Mobile View (<768px)
- Stacked table cells
- Full-width modal
- Touch-friendly buttons
- Scrollable tables

## 7. Color Scheme (Dark Theme)

### Colors Used
- **Background**: Dark gray (#212529)
- **Cards**: Slightly lighter dark (#343a40)
- **Primary Button**: Blue (#0d6efd)
- **Success Message**: Green (#198754)
- **Error Message**: Red (#dc3545)
- **Text**: Light gray/white
- **Icons**: Bootstrap Icons

### Button States
- **Upload Button**: Primary blue
- **Download Button**: Outline info (light blue border)
- **Delete Button**: Outline danger (red border)
- **Cancel Button**: Secondary gray

## 8. Accessibility Features

- Clear labels for all form fields
- Required field indicators (*)
- Help text for file input
- Keyboard navigation support
- Focus states on interactive elements
- Confirmation dialogs for destructive actions
- Screen reader friendly table structure

## 9. File Type Icons

Documents shown with appropriate icons:
- 📄 PDF files
- 🖼️ Image files (PNG, JPG, GIF)
- 📝 DOCX files
- 📭 Empty state

## 10. Animation & Transitions

- Modal fade in/out
- Success/error message slide in
- Button hover effects
- Loading states (if applicable)
- Smooth scrolling to messages

---

**Note**: This visual guide describes the intended appearance. The actual implementation uses Bootstrap 5 components styled with the dark theme to match the existing KManager application design.
