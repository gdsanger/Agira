# Blueprint Variable Recognition Fix - Implementation Summary

## Issue Overview
When applying blueprints to items in Agira, variables (placeholders in the format `{{ variable_name }}`) were not being fully recognized and processed. Specifically:

- ❌ Only the first variable found in the description was being asked for
- ❌ Variables in the **title** were completely ignored
- ❌ Multiple occurrences of the same variable were not being properly handled
- ❌ Validation only checked description, not title

## Solution Implemented

### 1. Backend Changes (Python)

#### New Utility Functions (`core/utils/blueprint_variables.py`)
```python
def extract_variables_from_multiple(texts: List[str]) -> List[str]:
    """
    Extract all unique variables from multiple text strings.
    Returns de-duplicated list in order of first appearance.
    """

def validate_variables_from_multiple(texts: List[str], provided_variables: Dict[str, str]) -> Tuple[bool, List[str]]:
    """
    Validate that all required variables from multiple texts are provided.
    Returns (is_valid, missing_variables)
    """
```

#### Updated Views (`core/views.py`)

**Before:**
```python
# Only validated description
is_valid, missing_vars = validate_variables(blueprint.description_md, variables)
```

**After:**
```python
# Validates both title and description
is_valid, missing_vars = validate_variables_from_multiple(
    [blueprint.title, blueprint.description_md],
    variables
)
```

### 2. Frontend Changes (JavaScript)

#### Apply Blueprint Modal (`templates/item_apply_blueprint_modal.html`)

**Before:**
```javascript
// Only extracted from description
const fullDescription = selectedOption.getAttribute('data-full-description');
while ((match = variablePattern.exec(fullDescription)) !== null) {
    // ...
}
```

**After:**
```javascript
// Extracts from both title and description
const title = selectedOption.getAttribute('data-title');
const fullDescription = selectedOption.getAttribute('data-full-description');

// Extract from title first
while ((match = variablePattern.exec(title)) !== null) {
    // ...
}
variablePattern.lastIndex = 0; // Reset for reuse

// Then extract from description
while ((match = variablePattern.exec(fullDescription)) !== null) {
    // ...
}
```

#### Other Templates
Similar changes were made to:
- `templates/blueprint_detail.html` (Create issue from blueprint modal)
- `templates/item_form.html` (Item creation form with blueprint selection)

### 3. Comprehensive Test Coverage

#### Unit Tests (`core/test_blueprint_variables.py`)
Added 9 new test cases:
- ✅ Extract from multiple texts with duplicates
- ✅ Extract from title and description
- ✅ Extract from empty texts
- ✅ Variables only in title
- ✅ Variables only in description
- ✅ Validate from multiple texts
- ✅ Validate missing variables across texts
- ✅ Validate title and description together

#### Integration Tests (`core/test_blueprint_extension.py`)
Added 4 new test cases:
- ✅ Apply blueprint with variables only in title
- ✅ Apply blueprint with variables in both title and description
- ✅ Missing title variables are caught in validation
- ✅ Create issue with title variables

**Total: 37 tests, all passing ✅**

## Example Scenario

### Before the Fix
**Blueprint:**
- Title: `Error in {{ entity }}`
- Description: `Please check {{ entity }} in {{ environment }}`

**User Experience:**
1. User selects blueprint
2. UI shows input field for `entity` only (from description)
3. User fills in `entity = "Database"`
4. Backend validation fails: "Missing required variables: environment"
5. **Title is never replaced** even if user managed to apply

### After the Fix
**Blueprint:**
- Title: `Error in {{ entity }}`
- Description: `Please check {{ entity }} in {{ environment }}`

**User Experience:**
1. User selects blueprint
2. UI shows 2 input fields:
   - `entity` (detected from both title and description)
   - `environment` (detected from description)
3. User fills in both:
   - `entity = "Database"`
   - `environment = "Production"`
4. Blueprint is applied successfully
5. **Result:**
   - Title: `Error in Database` ✅
   - Description: `Please check Database in Production` ✅

## Bug Fixes

### Fixed: Non-existent Field Bug
During implementation, discovered and fixed a bug in `blueprint_create_issue()` where code tried to use:
```python
item = Item.objects.create(
    created_by=request.user,  # ❌ This field doesn't exist on Item model
    # ...
)
```

This was causing 500 errors when creating issues from blueprints. Now fixed by removing the non-existent field.

## Security Analysis

✅ **CodeQL Security Scan: 0 Alerts**

No security vulnerabilities were introduced by this change. All input is properly validated and sanitized using existing mechanisms:
- Variables are extracted using regex pattern matching
- User input is validated before database operations
- HTML escaping is handled by Django templates

## Files Modified

1. `core/utils/blueprint_variables.py` - Added helper functions
2. `core/views.py` - Updated validation logic
3. `templates/item_apply_blueprint_modal.html` - Updated JS extraction
4. `templates/blueprint_detail.html` - Updated JS extraction
5. `templates/item_form.html` - Updated JS extraction
6. `core/test_blueprint_variables.py` - Added unit tests
7. `core/test_blueprint_extension.py` - Added integration tests

## Acceptance Criteria - COMPLETE ✅

- [x] Beim Anwenden eines Blueprints werden Variablen aus **Title und Description** erkannt
- [x] Für `n` unterschiedliche Variablen werden genau `n` Eingabefelder angezeigt
- [x] Eine Variable wird unabhängig von der Anzahl ihrer Vorkommen **nur einmal** abgefragt
- [x] Nach dem Anwenden sind **alle** Platzhalter in Title und Description ersetzt
- [x] Automatisierte Tests existieren für:
  - [x] Mehrere unterschiedliche Variablen
  - [x] Wiederholte Variablen
  - [x] Variablen nur im Title
  - [x] Variablen in Title + Description

## Next Steps

1. **Manual Testing** - Test the UI with real blueprints containing variables in titles
2. **User Acceptance** - Have users verify the fix meets their needs
3. **Documentation** - Update user documentation if needed to explain variable syntax in titles

## References

- Issue: gdsanger/Agira#330
- Related: gdsanger/Agira#435 (Blueprint Issues: Variablen/Parameter in Templates)
- Variable Syntax: `{{ variable_name }}` (only this format is supported)
