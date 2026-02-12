# Extended RAG Retrieval Pipeline Implementation Summary

## Overview

This document summarizes the implementation of an extended RAG (Retrieval-Augmented Generation) pipeline for the Agira project, as specified in Issue #384.

## Implementation Completed

### 1. Question Optimization Agent (`question-optimization-agent.yml`)

Created a specialized AI agent that analyzes and enriches user questions for improved retrieval:

**Input:** Raw user question or task description

**Output:** Structured JSON with:
- `language`: Detected language (e.g., "de", "en")
- `core`: Simplified core query (3-5 words, no filler words)
- `synonyms`: 3-5 relevant synonyms/alternative formulations
- `phrases`: 2-3 key phrases from the question
- `entities`: Named entities as JSON object (e.g., {"person": ["Max"], "product": ["Login"]})
- `tags`: 3-7 technical/domain tags for keyword search
- `ban`: Words to exclude from search (filler words)
- `followup_questions`: 1-3 potential follow-up questions

**Features:**
- Uses GPT-4o-mini for efficiency
- Includes response caching (600s TTL)
- Handles markdown code fences in responses
- Validates all required fields

### 2. Extended RAG Pipeline Service (`core/services/rag/extended_service.py`)

A comprehensive new service module implementing the advanced RAG pipeline:

#### Key Components:

**A. Question Optimization (`_optimize_question`)**
- Calls the question-optimization-agent
- Parses and validates JSON response
- Falls back to raw query on failure
- Removes markdown code fences from responses

**B. Dual Search Paths**

1. **Semantic/Hybrid Search** (`_build_semantic_query`, alpha=0.6)
   - Query: core + top 3 synonyms + top 2 phrases + top 2 tags
   - Retrieves up to 24 results
   - Balanced between vector and BM25

2. **Keyword/Tag Search** (`_build_keyword_query`, alpha=0.3)
   - Query: tags + core
   - Retrieves up to 24 results
   - BM25-focused (lower alpha = more keyword weight)

**C. Fusion and Reranking (`_fuse_and_rerank`)**
- Deduplicates results by `object_id`
- Calculates weighted final scores:
  - 60% semantic score
  - 20% BM25 score
  - 15% tag match bonus
  - 5% same-item bonus
- Sorts by score and type priority
- Returns top 6 results

**D. A/B/C-Layer Separation (`_separate_into_layers`)**
- **Layer A**: Thread/Task-related (2-3 snippets)
  - Comments and closely related items
- **Layer B**: Item context (2-3 snippets)
  - Same item or item-level context
- **Layer C**: Global background (1-2 snippets)
  - General context from projects and other sources

**E. Context Text Formatting**
- Generates LLM-friendly output with layer markers
- Format: `[#A1]`, `[#B1]`, `[#C1]`, etc.
- Includes relevance scores, links, and content snippets

#### Data Models:

**OptimizedQuery**
```python
@dataclass
class OptimizedQuery:
    language: str
    core: str
    synonyms: List[str]
    phrases: List[str]
    entities: Dict[str, List[str]]
    tags: List[str]
    ban: List[str]
    followup_questions: List[str]
    raw_response: Optional[str] = None
```

**ExtendedRAGContext**
```python
@dataclass
class ExtendedRAGContext:
    query: str
    optimized_query: Optional[OptimizedQuery]
    layer_a: List[RAGContextObject]  # Thread/Task
    layer_b: List[RAGContextObject]  # Item context
    layer_c: List[RAGContextObject]  # Global
    all_items: List[RAGContextObject]
    summary: str
    stats: Dict[str, Any]
    debug: Optional[Dict[str, Any]] = None
```

### 3. Updated Views

Modified 5 item-related views to use the extended pipeline:

1. **`item_optimize_description_ai`** (line ~1724)
   - Optimizes item descriptions for GitHub issues
   - Now uses `build_extended_context` with user tracking

2. **`item_generate_solution_ai`** (line ~1908)
   - Generates solution descriptions
   - Now uses `build_extended_context` with user tracking

3. **`item_pre_review`** (line ~2004)
   - Pre-reviews items using AI
   - Now uses `build_extended_context` with user tracking

4. **`item_rag_retrieval_raw`** (line ~2177)
   - Returns raw RAG results as Markdown
   - Updated to use `build_extended_context`
   - Enhanced `_format_rag_results_as_markdown` to handle both context types

5. **`item_answer_question_ai`** (line ~2540)
   - Answers open questions using AI
   - Now uses `build_extended_context` with user tracking

**Backward Compatibility:**
- API endpoint (`api_item_context`) kept with basic `build_context` for external system compatibility
- Both `RAGContext` and `ExtendedRAGContext` supported in formatting functions

### 4. Comprehensive Testing

Created `core/services/rag/test_extended_rag.py` with 19 comprehensive tests:

**Test Coverage:**
1. Question Optimization (4 tests)
   - Valid JSON response
   - Markdown code fence handling
   - Invalid JSON handling
   - Missing fields handling

2. Query Building (2 tests)
   - Semantic query construction
   - Keyword query construction

3. Search Execution (2 tests)
   - Weaviate unavailable handling
   - Result retrieval

4. Fusion and Reranking (3 tests)
   - Duplicate removal
   - Score calculation
   - Result limiting

5. Layer Separation (2 tests)
   - Correct type distribution
   - Size limit enforcement

6. Context Formatting (2 tests)
   - Layer marker presence
   - Score and link inclusion

7. Integration (4 tests)
   - Valid context generation
   - Optimization failure fallback
   - Skip optimization mode
   - Debug info inclusion

**Test Results:**
- ✅ All 19 new tests pass
- ✅ All 34 existing RAG tests pass (no regressions)

### 5. Security Analysis

**Code Review Results:**
- 2 minor comments found
- All comments addressed
- ✅ Code review clean

**CodeQL Security Scan:**
- 0 security alerts found
- ✅ No vulnerabilities detected

## Key Features

### 1. Smart Question Optimization
- Automatically enriches queries with synonyms and related terms
- Extracts technical tags for better keyword matching
- Identifies named entities for context-aware search

### 2. Parallel Retrieval Paths
- Semantic path optimized for natural language understanding
- Keyword path optimized for technical terms and tags
- Best of both worlds through intelligent fusion

### 3. Advanced Scoring
- Multi-factor relevance scoring
- Type-based prioritization
- Context-aware bonuses (e.g., same-item bonus)

### 4. Structured Context Layers
- Clear separation of context types (Thread, Item, Global)
- LLM-friendly formatting with explicit layer markers
- Controlled snippet distribution (A:3, B:3, C:2 max)

### 5. Graceful Degradation
- Fallback to raw query if optimization fails
- Handles Weaviate unavailability
- No breaking changes to existing functionality

## Usage Example

```python
from core.services.rag import build_extended_context

# Build extended context with all features
context = build_extended_context(
    query="Wie kann ich den Login-Bug mit Sonderzeichen beheben?",
    project_id="123",
    item_id="456",
    user=request.user,
    client_ip=request.META.get('REMOTE_ADDR')
)

# Access layered results
print(f"Layer A (Thread): {len(context.layer_a)} items")
print(f"Layer B (Item): {len(context.layer_b)} items")
print(f"Layer C (Global): {len(context.layer_c)} items")

# Get formatted context for LLM
context_text = context.to_context_text()
# Output includes [#A1], [#B1], [#C1] markers

# Access optimization results
if context.optimized_query:
    print(f"Core: {context.optimized_query.core}")
    print(f"Tags: {context.optimized_query.tags}")
    print(f"Synonyms: {context.optimized_query.synonyms}")

# Check statistics
print(f"Semantic results: {context.stats['sem_results']}")
print(f"Keyword results: {context.stats['kw_results']}")
print(f"Fused results: {context.stats['fused_results']}")
```

## Example Output

**Input Query:**
```
"Wie kann ich den Login-Bug mit Sonderzeichen im Passwort beheben?"
```

**Optimized Query:**
```json
{
  "language": "de",
  "core": "Login Bug Sonderzeichen Passwort",
  "synonyms": ["Anmeldung Fehler", "Authentication Problem", "Login-Fehler"],
  "phrases": ["Sonderzeichen im Passwort", "Login-Bug"],
  "entities": {"component": ["Login", "Passwort"]},
  "tags": ["login", "authentication", "bug", "password", "special-characters"],
  "ban": ["wie", "kann", "ich"],
  "followup_questions": ["Welche Sonderzeichen verursachen das Problem?"]
}
```

**Context Output:**
```
CONTEXT:
[#A1] (type=comment score=0.92) Password validation issue
       Link: /items/123/comments/456/
       User reported that special characters like ü, ö, ä cause login failures...

[#A2] (type=comment score=0.87) Related discussion
       Link: /items/124/comments/789/
       We should implement proper UTF-8 encoding in the password field...

[#B1] (type=item score=0.85) Login system refactoring
       Link: /items/123/
       Complete overhaul of authentication system with special character support...

[#C1] (type=project score=0.72) Authentication module
       Link: /projects/5/
       Project focusing on secure authentication and password handling...
```

## Files Modified/Created

### Created:
1. `agents/question-optimization-agent.yml` - AI agent configuration
2. `core/services/rag/extended_service.py` - Extended RAG pipeline service (618 lines)
3. `core/services/rag/test_extended_rag.py` - Comprehensive test suite (410 lines)

### Modified:
1. `core/services/rag/__init__.py` - Added exports for extended service
2. `core/views.py` - Updated 5 views to use extended pipeline
3. `.gitignore` - Added exception for question-optimization-agent.yml

## Technical Decisions

### 1. Alpha Values
- **Semantic search (0.6)**: Balanced, slight bias toward vector search
- **Keyword search (0.3)**: Strong BM25 bias for technical terms
- Rationale: Semantic for understanding context, keyword for exact matches

### 2. Fusion Scoring
- 60% semantic: Primary relevance indicator
- 20% BM25: Technical term matching
- 15% tag match: Domain relevance
- 5% same-item: Context continuity
- Rationale: Balanced approach favoring semantic understanding

### 3. Layer Distribution (A:3, B:3, C:2)
- Layer A (Thread): Most immediately relevant
- Layer B (Item): Direct context
- Layer C (Global): Background only
- Rationale: Focus on specific context, limit general information

### 4. Fallback Strategy
- Question optimization is optional (fails gracefully)
- Raw query used if optimization fails
- Rationale: Ensure service always works, even if AI agent fails

### 5. Backward Compatibility
- Kept API endpoint with basic pipeline
- Both context types supported in formatters
- Rationale: Don't break existing integrations

## Performance Considerations

1. **Parallel Searches**: Two Weaviate queries execute sequentially (potential for parallelization in future)
2. **Result Limit**: Fetches 24 results per search path (48 total) for fusion
3. **Deduplication**: O(n) time complexity with hash set
4. **Caching**: Question optimization responses cached for 600 seconds
5. **Agent Calls**: One additional AI call per request (mitigated by caching)

## Future Enhancements (Not in Scope)

1. True parallel execution of search paths
2. User feedback loop for relevance tuning
3. Custom layer distribution based on query type
4. Integration with additional data sources
5. Query expansion beyond synonyms
6. Multi-language optimization support
7. Performance metrics and monitoring
8. A/B testing framework for scoring weights

## Conclusion

The extended RAG pipeline successfully implements all requirements from Issue #384:

✅ Question optimization via AI agent with synonym/tag enrichment
✅ Dual search paths (semantic + keyword)
✅ Advanced fusion with custom scoring
✅ A/B/C-layer context bundling
✅ Integration with all item views
✅ Comprehensive testing (53 total tests passing)
✅ Security validated (0 vulnerabilities)
✅ Backward compatible

The implementation provides a robust foundation for enhanced RAG retrieval across the Agira platform, improving context quality for AI-powered features while maintaining system reliability and backward compatibility.
