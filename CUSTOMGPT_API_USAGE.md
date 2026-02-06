# CustomGPT Actions API Documentation

This document provides examples for using the Agira CustomGPT Actions API.

## Authentication

All API requests require the `x-api-secret` header with your API secret:

```bash
export CUSTOMGPT_API_SECRET="your-secret-here"
```

## API Endpoints

### Projects

#### List all projects
```bash
curl -X GET "http://localhost:8000/api/customgpt/projects" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET"
```

#### Get a specific project
```bash
curl -X GET "http://localhost:8000/api/customgpt/projects/1" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET"
```

#### Update a project (PUT - full replacement)
```bash
curl -X PUT "http://localhost:8000/api/customgpt/projects/1" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Project Name",
    "description": "Updated description",
    "status": "Working"
  }'
```

#### Update a project (PATCH - partial update)
```bash
curl -X PATCH "http://localhost:8000/api/customgpt/projects/1" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Only updating the description"
  }'
```

#### Get open items in a project
Returns all items with status != Closed
```bash
curl -X GET "http://localhost:8000/api/customgpt/projects/1/open-items" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET"
```

### Items

#### List all open items
Returns all items (across all projects) with status != Closed
```bash
curl -X GET "http://localhost:8000/api/customgpt/items" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET"
```

#### Get a specific item
```bash
curl -X GET "http://localhost:8000/api/customgpt/items/42" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET"
```

#### Update an item (PUT - full replacement)
```bash
curl -X PUT "http://localhost:8000/api/customgpt/items/42" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated Item Title",
    "description": "Updated description",
    "status": "Working"
  }'
```

#### Update an item (PATCH - partial update)
```bash
curl -X PATCH "http://localhost:8000/api/customgpt/items/42" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "Testing"
  }'
```

#### Create a new item in a project
```bash
curl -X POST "http://localhost:8000/api/customgpt/projects/1/items" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "New Item",
    "description": "Item description",
    "type_id": 1,
    "status": "Inbox"
  }'
```

#### Get RAG context for an item
Returns AI context from Weaviate vector database
```bash
curl -X GET "http://localhost:8000/api/customgpt/items/42/context" \
  -H "x-api-secret: $CUSTOMGPT_API_SECRET"
```

## Status Values

### Project Status
- `New`
- `Working`
- `Canceled`
- `Finished`

### Item Status
- `Inbox`
- `Backlog`
- `Working`
- `Testing`
- `ReadyForRelease`
- `Planing`
- `Specification`
- `Closed`

## Error Responses

### 401 Unauthorized
Missing or invalid `x-api-secret` header:
```json
{
  "error": "Unauthorized. Invalid or missing x-api-secret header."
}
```

### 404 Not Found
Resource not found:
```json
{
  "error": "Item not found"
}
```

### 400 Bad Request
Invalid payload:
```json
{
  "error": "title is required"
}
```

## OpenAPI Specification

The complete OpenAPI 3.0.3 specification is available at `/openapi.yaml` in the repository.
You can use this with tools like Swagger UI or import it into CustomGPT Actions.

## Testing

Run the test suite:
```bash
python manage.py test core.test_customgpt_api
```

All 18 tests should pass, covering:
- Authentication with x-api-secret header
- CRUD operations (no Delete)
- Status filtering for open items
- RAG context endpoint
