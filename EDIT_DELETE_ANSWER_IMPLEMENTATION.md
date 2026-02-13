# Edit and Delete Answer Implementation Summary

## Issue
**Issue #388**: "Bearbeiten von beantworteten Fragen" (Editing answered questions)
**Clarification**: "Es soll nicht die fragen bearbeitet werden, sondern die Antwort dazu" - The requirement is to edit/delete **answers**, not questions themselves.

## Overview
This implementation adds the ability to edit and delete answers to ItemQuestions after they have been answered. This complements PR #526 which already allows editing/deleting the question text itself.

## Changes Made

### Backend (Django)

#### New Endpoints (`core/urls.py`)
1. **`/open-questions/<question_id>/answer/edit/`** (POST)
   - Allows editing an existing answer
   - Can change answer type (free text ↔ standard answer)
   - Can update answer content

2. **`/open-questions/<question_id>/answer/delete/`** (POST)
   - Removes the answer from a question
   - Reverts question status to "Open"
   - Preserves the question itself

#### New View Functions (`core/views.py`)

##### `item_open_question_answer_edit(request, question_id)`
- **Purpose**: Edit an existing answer to an open question
- **Authentication**: Requires `@login_required`
- **HTTP Method**: POST
- **Request Body**:
  ```json
  {
    "answer_type": "free_text" | "standard_answer",
    "answer_text": "...",  // if answer_type is free_text
    "standard_answer_id": 123  // if answer_type is standard_answer
  }
  ```
- **Validations**:
  - Question must be in "Answered" status
  - Free text cannot be empty
  - Standard answer ID must be valid and active
- **Side Effects**:
  - Updates `answered_at` timestamp
  - Updates `answered_by` to current user
  - Syncs answered questions to item description
  - Logs activity: `item.open_question.answer_edited`

##### `item_open_question_answer_delete(request, question_id)`
- **Purpose**: Delete the answer to an open question, reverting it to Open status
- **Authentication**: Requires `@login_required`
- **HTTP Method**: POST
- **Behavior**:
  - Clears all answer fields: `answer_type`, `answer_text`, `standard_answer`, `answered_by`, `answered_at`
  - Sets status to `OpenQuestionStatus.OPEN`
  - Works for both "Answered" and "Dismissed" questions
- **Side Effects**:
  - Syncs answered questions to item description
  - Logs activity: `item.open_question.answer_deleted`

#### Updated View (`item_open_questions_list`)
- Added `standard_answer` object to JSON response
- Safely handles cases where `standard_answer` is `None`

### Frontend (HTML/JavaScript)

#### UI Changes (`templates/item_detail.html`)

##### Button Layout
For **Open Questions**:
- "Beantworten" (Answer)
- "Mit KI beantworten" (Answer with AI) - Agent role only
- "Als erledigt markieren" (Mark as done)
- "Frage bearbeiten" (Edit Question)
- "Frage löschen" (Delete Question)

For **Answered/Dismissed Questions**:
- "Antwort bearbeiten" (Edit Answer) - **NEW**
- "Antwort löschen" (Delete Answer) - **NEW**
- "Frage bearbeiten" (Edit Question)
- "Frage löschen" (Delete Question)

##### New Form: Edit Answer Form
- Pre-populated with current answer data
- Dropdown to select answer type (Standard/Free text)
- Conditional display of standard answer dropdown or free text area
- Save and Cancel buttons
- Hidden by default, shown when "Antwort bearbeiten" is clicked

##### New JavaScript Functions

**`showEditAnswerForm(questionId)`**
- Hides other open forms
- Shows the edit answer form for the specified question

**`hideEditAnswerForm(questionId)`**
- Hides the edit answer form

**`toggleEditAnswerInput(questionId)`**
- Toggles between standard answer dropdown and free text area
- Based on selected answer type

**`submitEditAnswer(questionId)`**
- Collects form data (answer type, content)
- Validates input (e.g., free text not empty)
- POSTs to `/open-questions/${questionId}/answer/edit/`
- Reloads questions on success

**`deleteAnswer(questionId)`**
- Shows confirmation dialog
- POSTs to `/open-questions/${questionId}/answer/delete/`
- Reloads questions on success (question will show as "Open")

### Tests (`core/test_open_questions.py`)

#### Test Class: `OpenQuestionAnswerEditTest`
6 test cases covering:
1. **`test_edit_answer_free_text_to_standard`** - Convert free text answer to standard answer
2. **`test_edit_answer_standard_to_free_text`** - Convert standard answer to free text
3. **`test_edit_answer_change_standard_answer`** - Change from one standard answer to another
4. **`test_edit_answer_requires_authentication`** - Verify login required
5. **`test_edit_answer_unanswered_question_fails`** - Cannot edit answer of unanswered question
6. **`test_edit_answer_validates_empty_free_text`** - Empty free text is rejected

#### Test Class: `OpenQuestionAnswerDeleteTest`
5 test cases covering:
1. **`test_delete_answer_free_text`** - Delete free text answer, verify status reverts to Open
2. **`test_delete_answer_standard`** - Delete standard answer, verify status reverts to Open
3. **`test_delete_answer_dismissed_question`** - Delete answer from dismissed question
4. **`test_delete_answer_requires_authentication`** - Verify login required
5. **`test_delete_answer_open_question_fails`** - Cannot delete answer of open question

**All 11 tests pass successfully.**

## Business Rules

1. **Editing Answers**:
   - Can change answer type (free text ↔ standard answer)
   - Can update answer content
   - Updates timestamp and author to reflect the edit
   - Only available for questions in "Answered" status

2. **Deleting Answers**:
   - Removes the answer completely
   - Reverts question to "Open" status
   - Question text remains unchanged
   - Available for both "Answered" and "Dismissed" questions

3. **Preservation**:
   - Editing a question does NOT delete its answer
   - Deleting an answer does NOT delete the question
   - All changes are logged to activity stream

## User Flow

### Editing an Answer
1. User views item with answered questions
2. Clicks "Antwort bearbeiten" (Edit Answer) button
3. Edit form appears with current answer pre-filled
4. User modifies answer or changes type
5. Clicks "Änderung speichern" (Save Changes)
6. Answer is updated, page refreshes to show new answer

### Deleting an Answer
1. User views item with answered questions
2. Clicks "Antwort löschen" (Delete Answer) button
3. Confirmation dialog appears
4. User confirms deletion
5. Answer is removed, question reverts to "Open" status
6. Page refreshes, question now shows as open/unanswered

## API Examples

### Edit Answer (Free Text)
```bash
POST /open-questions/123/answer/edit/
Content-Type: application/json

{
  "answer_type": "free_text",
  "answer_text": "This is my updated answer"
}
```

**Response:**
```json
{
  "success": true,
  "status": "Answered",
  "answer": "This is my updated answer"
}
```

### Edit Answer (Standard Answer)
```bash
POST /open-questions/123/answer/edit/
Content-Type: application/json

{
  "answer_type": "standard_answer",
  "standard_answer_id": 2
}
```

### Delete Answer
```bash
POST /open-questions/123/answer/delete/
Content-Type: application/json
```

**Response:**
```json
{
  "success": true,
  "question_id": 123,
  "status": "Open"
}
```

## Security

- All endpoints require authentication (`@login_required`)
- CSRF protection via Django's CSRF tokens
- Input validation:
  - Answer type must be valid enum value
  - Free text cannot be empty
  - Standard answer must exist and be active
- No SQL injection vulnerabilities (uses Django ORM)
- **CodeQL Analysis**: 0 security alerts found

## Activity Logging

All answer modifications are logged to the activity stream:
- **`item.open_question.answer_edited`**: When an answer is edited
- **`item.open_question.answer_deleted`**: When an answer is deleted

## Compatibility

- Compatible with existing question edit/delete functionality (PR #526)
- Maintains backward compatibility with AI answer generation
- Works with both free text and standard answers
- Supports dismissed questions (can delete dismissal)

## Files Modified

1. **`core/urls.py`** - Added 2 new URL patterns
2. **`core/views.py`** - Added 2 new view functions, updated 1 existing view
3. **`templates/item_detail.html`** - Added buttons, forms, and JavaScript functions
4. **`core/test_open_questions.py`** - Added 11 new test cases

## Testing

Run tests with:
```bash
python manage.py test core.test_open_questions.OpenQuestionAnswerEditTest core.test_open_questions.OpenQuestionAnswerDeleteTest
```

All 11 tests pass successfully.

## Related Issues/PRs

- **Issue #525**: Original issue (later clarified)
- **PR #526**: Added ability to edit/delete questions (not answers)
- **Issue #388**: Current issue - edit/delete answers (not questions)
- Referenced issues: #342, #344, PR #345 (related to Open Questions feature)
