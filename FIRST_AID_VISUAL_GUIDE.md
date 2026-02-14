# First AID - Visual Guide

## UI Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Agira - First AID                               │
├─────────────────────────────────────────────────────────────────────────┤
│  Project:  [Select a project...                      ▼]                  │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────┬───────────────────────────────────┬─────────────────┐
│   📁 Sources    │          💬 Chat                  │   🛠️ Tools     │
│   (300px)       │         (Fluid)                   │   (280px)       │
├─────────────────┼───────────────────────────────────┼─────────────────┤
│                 │                                   │                 │
│ 📋 Items (5)    │  ┌─────────────────────────────┐ │ ┌─────────────┐ │
│ ┌─────────────┐ │  │ First AID                   │ │ │ 📝 Generate │ │
│ │ #1: Bug fix │ │  │ Hello! I'm your AI...       │ │ │ KB Article  │ │
│ │ Description │ │  │ Ask me anything about...    │ │ └─────────────┘ │
│ └─────────────┘ │  └─────────────────────────────┘ │                 │
│                 │                                   │ ┌─────────────┐ │
│ 🐙 GitHub       │  ┌─────────────────────────────┐ │ │ 📄 Generate │ │
│ Issues (3)      │  │ You                         │ │ │ Docs        │ │
│ ┌─────────────┐ │  │ What is this project?       │ │ └─────────────┘ │
│ │ GH Issue #2 │ │  └─────────────────────────────┘ │                 │
│ │ Title...    │ │                                   │ ┌─────────────┐ │
│ └─────────────┘ │  ┌─────────────────────────────┐ │ │ 🧠 Generate │ │
│                 │  │ First AID                   │ │ │ Flashcards  │ │
│ 🔀 GitHub       │  │ This project is about...    │ │ └─────────────┘ │
│ PRs (2)         │  └─────────────────────────────┘ │                 │
│ ┌─────────────┐ │                                   │ ┌─────────────┐ │
│ │ GH PR #1    │ │  ┌─────────────────────────────┐ │ │ 🐞 Create   │ │
│ │ Title...    │ │  │ [Type your question...]     │ │ │ Issue       │ │
│ └─────────────┘ │  │                      [Send] │ │ └─────────────┘ │
│                 │  └─────────────────────────────┘ │                 │
│ 📎 Attachments  │                                   │                 │
│ (4)             │                                   │ ┌─────────────┐ │
│ ┌─────────────┐ │                                   │ │   Result    │ │
│ │ doc.pdf     │ │                                   │ │   Area      │ │
│ │ PDF - 120KB │ │                                   │ │             │ │
│ └─────────────┘ │                                   │ │             │ │
│                 │                                   │ └─────────────┘ │
│ (Sticky)        │  (Scrollable)                     │ (Sticky)        │
└─────────────────┴───────────────────────────────────┴─────────────────┘
```

## Color Scheme (Dark Theme)

- **Background**: Dark gray (#212529)
- **Panels**: Slightly lighter dark (#2d3238)
- **Borders**: Bootstrap border color
- **Primary**: Bootstrap primary blue
- **User Messages**: Primary blue background
- **AI Messages**: Secondary background
- **Icons**: Bootstrap icons with contextual colors
  - Sources: Blue/Info
  - Heart icon: Red (text-danger)
  - Tools: Primary/Outline

## Key Features Visible

### Left Panel - Sources
- **Header**: "📁 Sources" with count badges
- **Sections**:
  - 📋 Items (with count)
  - 🐙 GitHub Issues (with count)
  - 🔀 GitHub PRs (with count)
  - 📎 Attachments (with count)
- **Source Cards**:
  - Title (truncated)
  - Description preview
  - External link icon
  - Clickable to add to context
  - Selected state (highlighted)

### Middle Panel - Chat
- **Welcome Message**: Introduces capabilities
- **User Messages**: Right-aligned, blue background
- **AI Messages**: Left-aligned, gray background
- **Input Area**:
  - Text input field
  - Send button with icon
  - Disabled when no project selected
- **Loading States**: Spinner during processing
- **Error Display**: Red alert for errors

### Right Panel - Tools
- **Header**: "🛠️ Tools"
- **Tool Buttons** (full width):
  - 📝 Generate KB Article
  - 📄 Generate Documentation
  - 🧠 Generate Flashcards
  - 🐞 Create Issue
  - All disabled when no project selected
- **Result Area**:
  - Shows generated content
  - Download button for markdown files
  - Scrollable for long content

## Responsive Behavior

### Desktop (≥768px)
```
┌────────────────────────────────────────────┐
│         3-Column Layout                     │
│  [Sources] [Chat] [Tools]                   │
│   Fixed     Fluid  Fixed                    │
└────────────────────────────────────────────┘
```

### Mobile (<768px)
```
┌──────────────────────┐
│  Project Selector    │
├──────────────────────┤
│  [Tab: Sources]      │
│  [Tab: Chat]         │
│  [Tab: Tools]        │
├──────────────────────┤
│                      │
│  Active Tab Content  │
│                      │
└──────────────────────┘
```

## User Interaction Flow

### 1. Initial Load
```
User arrives → Sees project selector → Sidebar shows "First AID" link
```

### 2. Project Selection
```
User selects project → Sources load via HTMX → Chat enabled → Welcome message appears
```

### 3. Chat Interaction
```
User types question → Clicks Send → Loading spinner → AI response → Context stored
```

### 4. Using Tools
```
User clicks tool button → Context validated → Loading spinner → Result displayed → Download option
```

### 5. Creating Issue
```
User clicks "Create Issue" → Last Q&A used → Item created → Success message + link
```

## Navigation Integration

```
Sidebar (AI/KI Section):
├── ❤️‍🩹 First AID (NEW - highlighted in red)
├── 🤖 AI Providers
├── 🎭 AI Agents
└── 🕐 AI Jobs History
```

## Icon Legend

- ❤️‍🩹 `bi-heart-pulse-fill` - First AID main icon (red)
- 📁 `bi-folder2-open` - Sources section
- 💬 Chat bubble - Chat section
- 🛠️ `bi-tools` - Tools section
- 📋 `bi-list-task` - Items
- 🐙 `bi-github` - GitHub Issues
- 🔀 `bi-git` - GitHub PRs
- 📎 `bi-paperclip` - Attachments
- 📝 `bi-journal-text` - KB Article
- 📄 `bi-file-earmark-text` - Documentation
- 🧠 `bi-card-heading` - Flashcards
- 🐞 `bi-bug` - Create Issue
- 📤 `bi-send` - Send button
- 🔗 `bi-box-arrow-up-right` - External link
- 👁️ `bi-eye` - View attachment
- 💾 `bi-download` - Download

## Example Scenarios

### Scenario 1: Asking About Project
```
User: "What is this project about?"
AI: "Based on the available context from 5 items, 3 issues, 
     and 4 documentation files, this project is a task 
     management system with AI capabilities..."
```

### Scenario 2: Generating Documentation
```
User: [Has chat history about feature X]
Click: "Generate Documentation"
Result: # Feature X Documentation
        
        ## Overview
        Feature X provides...
        
        ## Usage
        To use Feature X...
        
        [Download Button]
```

### Scenario 3: Creating Issue
```
User: "We need to add support for dark mode"
AI: "Dark mode could improve user experience..."
Click: "Create Issue"
Result: ✅ Issue created!
        View Issue #123
```

## Technical Notes

- **HTMX**: Used for source loading without page reload
- **JavaScript**: Manages chat context and tool interactions
- **CSRF**: Automatically handled via meta tag
- **Loading States**: Spinners and disabled states
- **Error Handling**: User-friendly error messages
- **Accessibility**: Proper ARIA labels and semantic HTML
- **Performance**: Lazy loading, limits on source counts

## Future Enhancements Preview

### Potential Additions (Not in MVP)
```
┌─────────────────────────────────────┐
│ 🎬 Generate Video Script            │
│ 🎵 Generate Audio Transcript        │
│ 📊 Create Quiz                       │
│ 🎨 Generate Presentation             │
│ 🧠 Generate Mindmap                  │
│ 🔍 Advanced Source Filtering         │
│ 💾 Save Chat Sessions                │
│ 📤 Export Chat History               │
└─────────────────────────────────────┘
```

---

**Note**: This visual guide represents the UI structure. The actual implementation is complete and functional. Access it via the sidebar menu under AI/KI → First AID.
