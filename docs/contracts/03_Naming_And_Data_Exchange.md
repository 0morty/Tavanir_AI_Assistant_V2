# Naming & Data Exchange Conventions for Tavanir AI Assistant V2

## General Principle

All data exchanged between the upstream Tavanir suggestion system (caller) and the **Tavanir AI Assistant V2** service (RAG backend) must use **`camelCase`**, consistently, everywhere.

This requirement covers all data that moves on the path between caller and service:

- `request payload`
- `response`
- `query string`
- `path params`
- `body`
- `form data` (metadata)
- `nested objects`
- `arrays of objects`

---

## Header Rule (Exception)

HTTP headers (standard and custom) follow **`Title-Case`** style:

- `X-API-Key`
- `X-Request-Id`
- `Content-Type`
- `Authorization`

---

## Main Rule

1. All payload field names must be `camelCase`.
2. This applies across all communication layers: request, response, URL params, query string, body, and nested objects.

---

## Examples

### 1. Body — Analyze Suggestion Request

**Correct:**

```json
{
  "title": "عدم پرداخت مابه‌التفاوت افزایش حقوق",
  "currentProblem": "وضعیت فعلی ...",
  "solution": "راهکار پیشنهادی ...",
  "contextTitle": "امور مالی"
}
```

**Incorrect:**

```json
{
  "title": "عدم پرداخت مابه‌التفاوت افزایش حقوق",
  "current_problem": "وضعیت فعلی ...",
  "solution": "راهکار پیشنهادی ...",
  "context_title": "امور مالی"
}
```

### 2. Body — Analyze Suggestion Response

Maps directly from `AnalyzeSuggestionResponse` (`src/application/dtos.py`):

**Correct:**

```json
{
  "analysis": "## توصیه نهایی ...",
  "similarExecutedIds": ["sug-1", "sug-2"],
  "similarApprovedIds": [],
  "similarPendingIds": ["sug-9"],
  "similarRejectedIds": ["sug-3"],
  "similarNotAcceptedIds": [],
  "appliedStatuteIds": ["stat-4", "stat-7"]
}
```

### 3. Body — Real-time Ingestion (single suggestion)

**Correct:**

```json
{
  "suggestionId": "sug-42",
  "title": "عنوان پیشنهاد",
  "currentProblem": "مشکل موجود",
  "solution": "راه حل پیشنهادی",
  "contextTitle": "امور فنی",
  "status": "EXECUTED"
}
```

Status values are the canonical `SuggestionStatus` member names (see mapping below).

### 4. Body — Suggestion Deletion (bulk)

**Correct:**

```json
{
  "suggestionIds": ["sug-1", "sug-2", "sug-3"]
}
```

### 5. Query String

**Correct:**

```http
GET /analyze-suggestion/status?includeRetry=true
```

**Incorrect:**

```http
GET /analyze-suggestion/status?include_retry=true
```

### 6. Path Params

**Correct:**

```http
GET /analyze-suggestion/{suggestionId}
```

```text
const { suggestionId } = req.params;
```

### 7. Headers (custom)

```http
X-API-Key: <SECRET>
X-Request-Id: 123e4567-e89b-12d3-a456-426614174000
```

---

## Status Canonical Values

The `SuggestionStatus` enum (`src/domain/enums.py`) defines the five statuses. The **member name** is the stable wire identifier; the Persian title is the presentation-layer display string:

| Wire code (`name`) | Persian title (`title_fa`) | Legacy `status_id` |
| ------------------ | -------------------------- | ------------------ |
| `NOT_ACCEPTED`     | عدم پذیرش                  | 1                  |
| `REJECTED`         | رد                         | 2                  |
| `APPROVED`         | مصوب                       | 3                  |
| `PENDING`          | در حال اجرا                | 4                  |
| `EXECUTED`         | اجرا شده                   | 5                  |

---

## Important Notes

1. All teams must honor `camelCase` for request/response bodies.
2. Custom headers are always `Title-Case`.
3. If a library produces `snake_case` output (e.g. an ORM or a dataclass DTO), it must be converted to `camelCase` before being sent to the caller.
4. This contract is valid for all endpoints, DTOs, schemas, and payloads.
5. The mapping between internal `snake_case` models and the external `camelCase` contract must be centralized in the Presentation layer.
