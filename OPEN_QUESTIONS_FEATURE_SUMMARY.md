# Feature Implementation: Offene Fragen aus KI-Antworten sichtbar machen & iterativ beantworten

## Overview
This implementation adds support for managing open questions identified by AI agents when creating or optimizing issues. Questions are cleanly separated from issue content, visibly displayed, and can be iteratively answered.

## Implementation Summary

### 1. Data Models

#### IssueStandardAnswer
- Configurable standard answers for quick question responses
- Fields: key, label, text, is_active, sort_order
- Initial answers created via data migration:
  - `project_context`: "Ergibt sich aus dem Projektkontext"
  - `copilot_decides`: "Copilot kann das selbst entscheiden"
  - `default_behavior`: "Standardverhalten der Anwendung"
  - `not_relevant`: "Nicht relevant / ignorieren"

#### IssueOpenQuestion
- Tracks open questions about issues
- Fields: issue (FK), question, status, answer_text, answer_type, standard_answer, source, timestamps, answered_by, sort_order
- Status types: Open, Answered, Dismissed
- Answer types: FreeText, StandardAnswer, None
- Source types: AIAgent, Human
- Questions are never deleted, only status changes (maintains history)
- Prevents duplicate open questions with identical text

### 2. AI Agent Response Contract

The AI agent must return responses in the following JSON format:

```json
{
  "issue": {
    "description": "Full issue text (Markdown)"
  },
  "open_questions": [
    "Question 1",
    "Question 2"
  ]
}
```

**Processing Rules:**
- Only `issue.description` is used for the issue description
- `open_questions` are stored separately in IssueOpenQuestion
- Fallback to plain text if JSON parsing fails
- Duplicate questions (same text, status=Open) are not created

### 3. API Endpoints

#### GET /items/<item_id>/open-questions/
Returns list of all questions for an item with available standard answers.

Response:
```json
{
  "success": true,
  "questions": [...],
  "standard_answers": [...],
  "has_open": boolean
}
```

#### POST /open-questions/<question_id>/answer/
Answer or dismiss a question.

Request body examples:

**Answer with standard answer:**
```json
{
  "action": "answer",
  "answer_type": "standard_answer",
  "standard_answer_id": 1
}
```

**Answer with free text:**
```json
{
  "action": "answer",
  "answer_type": "free_text",
  "answer_text": "Custom answer text"
}
```

**Dismiss question:**
```json
{
  "action": "dismiss"
}
```

### 4. UI Changes

#### Item Detail Page (templates/item_detail.html)

**Warning Banner:**
- Displayed when issue has open questions (status=Open)
- Shows: "⚠️ Achtung: Dieses Issue enthält offene Fragen"
- Bootstrap alert styling (yellow warning)

**Offene Fragen Section:**
- Card-based display below item description
- Shows all questions with status badges
- Open questions show action buttons:
  - "Beantworten" - opens answer form
  - "Als erledigt markieren" - dismisses question
- Answer form allows:
  - Selection of standard answer from dropdown
  - OR free text input
  - Cancel button
- Answered/Dismissed questions show:
  - Answer text
  - Who answered and when
  - Checkmark icon

**JavaScript Functions:**
- `loadOpenQuestions()` - Fetches and renders questions
- `showAnswerForm(id)` / `hideAnswerForm(id)` - Toggle answer UI
- `toggleAnswerInput(id)` - Switch between standard/free text
- `submitAnswer(id)` - Submit answer via AJAX
- `dismissQuestion(id)` - Dismiss via AJAX
- Auto-loads on page load

### 5. Django Admin Integration

**IssueStandardAnswerAdmin:**
- List view: label, key, is_active, sort_order
- Editable in list: is_active, sort_order
- Searchable by label, key, text
- Filterable by is_active

**IssueOpenQuestionAdmin:**
- List view: question (short), issue, status, source, answered_by, created_at
- Filterable by status, source, date
- Searchable by question, answer_text, issue title
- Readonly: timestamps

**IssueOpenQuestionInline:**
- Added to ItemAdmin as inline
- Shows questions directly on item detail page
- Fields: question, status, answer_type, source, answered_by, answered_at
- Cannot be deleted (maintains history)

### 6. Migrations

**0034_add_open_questions_models.py:**
- Creates IssueStandardAnswer model
- Creates IssueOpenQuestion model
- Adds indexes for performance

**0035_add_initial_standard_answers.py:**
- Data migration
- Creates 4 initial standard answers (German)
- Reversible migration

### 7. Testing

**core/test_open_questions.py:**
- 18 comprehensive test cases
- Coverage includes:
  - Model creation and behavior
  - String representations
  - Answer display methods
  - AI optimization with JSON parsing
  - Duplicate question prevention
  - API endpoint authentication
  - Standard answer selection
  - Free text answers
  - Question dismissal
  - Error handling

## Security Summary

✅ **CodeQL Analysis:** No vulnerabilities found  
✅ **Code Review:** No issues identified

**Security Measures:**
- CSRF protection on all POST endpoints
- Authentication required for all endpoints
- Input validation on all API calls
- XSS protection via Django's template escaping
- SQL injection protection via Django ORM
- No sensitive data exposure

## Files Changed

1. `core/models.py` - New models and enums
2. `core/views.py` - Updated AI view, new API endpoints
3. `core/urls.py` - New URL patterns
4. `core/admin.py` - Admin configuration
5. `templates/item_detail.html` - UI for open questions
6. `core/migrations/0034_add_open_questions_models.py` - Schema migration
7. `core/migrations/0035_add_initial_standard_answers.py` - Data migration
8. `core/test_open_questions.py` - Test suite

## Acceptance Criteria Met

✅ Issue-Description contains only factual work content  
✅ Open questions are clearly separated and visible  
✅ Warning appears when open questions exist  
✅ Answers are historically preserved  
✅ No JSON or meta-text in issue description  
✅ Standard answers available for quick responses  
✅ Free text answers supported  
✅ Questions can be dismissed  
✅ All data persisted (nothing deleted)  
✅ UI shows question status clearly  
✅ Copilot can use context from answered questions

## Non-Goals (As Specified)

❌ No automatic AI agent re-runs  
❌ No automatic issue re-creation  
❌ No email notifications  

## Usage Example

1. **Agent optimizes issue description:**
   ```python
   POST /items/123/ai/optimize-description/
   ```
   
2. **AI returns JSON with questions:**
   ```json
   {
     "issue": {"description": "# Bug Fix\n\nDetailed description..."},
     "open_questions": ["What about edge case X?"]
   }
   ```

3. **Question appears in UI with warning banner**

4. **User answers question:**
   - Selects standard answer "Copilot decides"
   - OR enters free text
   - Clicks "Antwort speichern"

5. **Question marked as answered, visible in history**

## Future Enhancements (Not in Scope)

- Automatic appending of answered questions to issue description
- Email notifications when questions are answered
- Question templates
- Question priority/severity
- Question assignment to specific users
- Integration with GitHub issue sync

## Conclusion

This implementation fully addresses the requirements specified in Issue #225. All acceptance criteria are met, security checks pass, and comprehensive tests ensure reliability. The feature is production-ready and maintains backward compatibility with existing functionality.
