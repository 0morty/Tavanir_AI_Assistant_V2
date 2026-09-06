# JSON API Response Conventions for Tavanir AI Assistant V2

The response model is designed around the **JSON:API** standard so that every response type (success and failure) is uniform and predictable.

---

## Models

### 1) Fail :: Single error

- HTTP status: the actual error code (e.g. 404 or 422)
- Body:

```json
{
  "errors": [
    {
      "status": "<HTTP_STATUS_CODE>",
      "code": "<INTERNAL_CODE>",
      "source": { "pointer": "<JSON_POINTER_TO_FIELD_OR_RESOURCE>" },
      "debug": {
        "exception": "<EXCEPTION NAME>",
        "cause": "<OPTIONAL - ORIGINAL ERROR>",
        "stack_trace": "<STACK TRACE>"
      }
    }
  ]
}
```

---

### 2) Fail :: Multi error

- HTTP status: 400 Bad Request
- `errors[]` holds several errors from different resources or fields
- Each error may carry a `debug` field (based on the environment: dev / staging / test; stripped in prod)

```json
{
  "errors": [
    {
      "status": 422,
      "code": "<INTERNAL_CODE>",
      "source": { "pointer": "/data/0/title" }
    },
    {
      "status": 500,
      "code": "<INTERNAL_CODE>",
      "source": { "pointer": "/data/1" },
      "debug": {
        "exception": "EmbedderAPIError",
        "cause": "Provider timeout",
        "stack_trace": "..."
      }
    }
  ]
}
```

---

### 3) Success :: Single & Multi

- HTTP status: 2xx
- Body includes `status` and `data`; `data` can be an object or an array.

```json
{
  "status": 200,
  "data": {}
}
```
or
```json
{
  "status": 200,
  "data": [{}, {}, {}]
}
```

> **Note:** For asynchronous accept responses, the service uses `202 Accepted`. The unified shape for this model is:
> ```json
> {
>   "status": 202,
>   "data": { "message": "queued", "suggestionId": "sug-42" }
> }
> ```

---

## Conventions

### 1) Partial Success (mixed result)

In batch or asynchronous processing scenarios, a response can contain both successful items (`data`) and failed items (`errors`):
- `data` → successful items
- `errors[]` → failed items

### 2) Use of `source.pointer`

- For request fields: points to the exact field (e.g. `/data/title`).
- For resources: points to `/data` or `/data/{index}`.
- For external-service or general errors: can be `/data` or empty.

### 3) The `debug` Field

- Contains `exception`, `cause`, and `stack_trace`.
- **Security note:** in **production**, the `debug` field is not rendered.

### 4) Status Codes

- Single fail → the actual error code (404, 422, 401, ...)
- Multi fail → always 400
- Success → 2xx

### 5) The JSON:API Standard

Uses the `errors[]`, `source.pointer`, and `status` fields.

---

## Examples

### 1) Fail :: Single — Suggestion not found

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "errors": [
    {
      "status": 404,
      "code": "SUGGESTION_NOT_FOUND",
      "source": { "pointer": "/data" }
    }
  ]
}
```

### 2) Fail :: Single — Status not recognized

```http
HTTP/1.1 422 Unprocessable Entity

{
  "errors": [
    {
      "status": 422,
      "code": "INVALID_SUGGESTION_STATUS",
      "source": { "pointer": "/data/status" }
    }
  ]
}
```

### 3) Fail :: Single — Missing required field

```http
HTTP/1.1 422 Unprocessable Entity

{
  "errors": [
    {
      "status": 422,
      "code": "MISSING_REQUIRED_FIELD",
      "source": { "pointer": "/data/title" }
    }
  ]
}
```

### 4) Fail :: Single — Invalid API key

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: ApiKey

{
  "errors": [
    {
      "status": 401,
      "code": "API_KEY_INVALID",
      "source": { "pointer": "/headers/X-API-Key" }
    }
  ]
}
```

### 5) Fail :: Multi — batch ingestion errors

```http
HTTP/1.1 400 Bad Request

{
  "errors": [
    {
      "status": 400,
      "code": "PAYLOAD_MISMATCH",
      "source": { "pointer": "/data/suggestionIds" }
    },
    {
      "status": 409,
      "code": "SUGGESTION_ALREADY_INGESTED",
      "source": { "pointer": "/data/0" }
    },
    {
      "status": 500,
      "code": "EMBEDDING_FAILED",
      "source": { "pointer": "/data/1" },
      "debug": { "exception": "EmbedderAPIError", "cause": "Provider unreachable" }
    }
  ]
}
```

### 6) Fail :: Single — delete while processing

```http
HTTP/1.1 409 Conflict

{
  "errors": [
    {
      "status": 409,
      "code": "SUGGESTION_IN_PROCESSING",
      "source": { "pointer": "/data" }
    }
  ]
}
```

### 7) Success :: Single — analysis result

```http
HTTP/1.1 200 OK

{
  "status": 200,
  "data": {
    "analysis": "## توصیه نهایی ...",
    "similarExecutedIds": ["sug-1"],
    "similarApprovedIds": [],
    "similarPendingIds": [],
    "similarRejectedIds": [],
    "similarNotAcceptedIds": [],
    "appliedStatuteIds": ["stat-4"]
  }
}
```

---

## Notes

1. The `status` and `code` fields are mandatory in every error.
2. `source.pointer` links the error to the specific field or resource in the request.
3. Single fail → its own code; Multi fail → 400; Success → 2xx.
4. Internal codes (`code`) must be picked from the internal-code dictionary (file 05).