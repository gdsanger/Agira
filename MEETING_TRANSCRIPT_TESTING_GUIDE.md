# Meeting Transcript Upload - Manual Testing Guide

## Prerequisites
1. User must be logged in with 'Agent' role
2. A Meeting item must exist (Item with type='meeting')
3. A .docx file containing meeting transcript text
4. ItemType 'task' must exist in the database

## Test Scenario 1: Successful Upload
**Steps:**
1. Navigate to a Meeting item detail page
2. Verify the "Transkript importieren" button is visible in the Description section (yellow/warning outline)
3. Click the button to open file picker
4. Select a .docx file containing a meeting transcript
5. Wait for processing (spinner will show)

**Expected Result:**
- Success toast notification appears
- Page reloads automatically
- Meeting Description is updated with the AI-generated summary
- New Task items appear as child items under the meeting
- Each task has:
  - Status: Inbox
  - AssignedTo: Current user
  - Requester: Empty
  - Parent: The meeting item

## Test Scenario 2: Non-Meeting Item
**Steps:**
1. Navigate to a non-meeting item (e.g., Bug, Feature)
2. Look for the "Transkript importieren" button

**Expected Result:**
- Button is NOT visible (only shows for Meeting items)

## Test Scenario 3: Invalid File Type
**Steps:**
1. Navigate to a Meeting item
2. Click "Transkript importieren"
3. Select a non-.docx file (e.g., .pdf, .txt, .doc)

**Expected Result:**
- Error toast: "Bitte nur .docx Dateien hochladen"
- No upload occurs
- Meeting remains unchanged

## Test Scenario 4: Empty Tasks
**Steps:**
1. Upload a .docx file with brief meeting content that has no clear action items
2. Wait for processing

**Expected Result:**
- Success notification
- Meeting Description is updated with summary
- No task items are created (tasks_created = 0)

## Test Scenario 5: Agent Error
**Steps:**
1. If AI agent is unavailable or returns invalid JSON
2. Upload a valid .docx file

**Expected Result:**
- Error toast: "Fehler beim Verarbeiten des Transkripts" 
- Meeting Description is NOT changed
- No task items are created

## Sample Test Document Content
Create a .docx file with content like:

```
Meeting Notes - Project Kickoff
Date: January 30, 2026

Participants discussed the new feature requirements. Key points:
- Review timeline and milestones
- Assign responsibilities to team members
- Schedule follow-up meetings

Action Items:
1. John to prepare the technical specification document by Friday
2. Sarah to coordinate with the design team for UI mockups
3. Team to review and provide feedback on the project plan by end of week
```

## Validation Checklist
- [ ] Button only visible for Meeting items
- [ ] Button only visible for Agent role users
- [ ] File picker accepts only .docx files
- [ ] Upload spinner shows during processing
- [ ] Success/error notifications appear appropriately
- [ ] Meeting Description is overwritten (not appended)
- [ ] Tasks created as child items with correct fields
- [ ] Activity log shows upload and update events
- [ ] Attachment is saved and visible in Attachments tab

## Known Limitations
- Only .docx format supported (not .doc, .pdf, or other formats)
- Requires OpenAI API to be configured for the get-meeting-details agent
- Button only visible to users with 'Agent' role
- Meeting description is completely overwritten (previous content is lost)
