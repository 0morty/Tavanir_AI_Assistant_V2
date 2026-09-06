# Authentication & Caller Identity Convention for Tavanir AI Assistant V2

## Goal

To standardize service access to the **Tavanir AI Assistant V2**, this document defines how the caller (the upstream Tavanir suggestion system) authenticates and how requests are identified.

> **Note on current state:** `src/presentation/security.py` is not implemented yet. This document is the **target contract** for service-level authentication when the HTTP layer is built.

> **Responsibility boundary:** The V2 service is a stateless backend. All user logic, authentication, and permission decisions happen in the upstream Tavanir system; the service does **not** implement a user/session layer.

---

## 1. API Key based Authentication

All requests to the service must carry the following header:

```http
X-API-Key: <SECRET>
```

### Rules

- Sending `X-API-Key` is **mandatory** for all protected endpoints.
- The key value is compared on the server side against a securely configured value (constant-time comparison).
- Missing or invalid key → `401 Unauthorized` response with `WWW-Authenticate: ApiKey`.
- The API key must never appear in URLs, logs, or publicly accessible error messages.

### Sample request

```http
POST /ingest-suggestion/ingest
X-API-Key: <SECRET>
Content-Type: application/json
```

---

## 2. Caller Identification

### `X-Request-Id` (optional but recommended)

For distributed tracing and monitoring, the caller can send a unique identifier. Otherwise the service generates a Correlation ID and reflects it in the response and logs.

```http
X-Request-Id: 123e4567-e89b-12d3-a456-426614174000
```

This id is used only for logging, monitoring, and analysis; it has no effect on business logic.

---

## 3. No Session / Cookie / CSRF

Unlike end-user (Web/Mobile) systems, the V2 service:

- is **stateless** and manages no Session or Cookie,
- authenticates every request via `X-API-Key`,
- does not use cookie-based auth, so the **CSRF** concept is meaningless here and no CSRF token is needed,
- performs all communication as **service-to-service** between the upstream Tavanir system and itself.

> If a browser-based interface (e.g. an internal dashboard) is added in the future, a separate authentication model will be documented; this contract will not cover it except via a separate addendum.

---

## 4. Contract Summary

| Item | Value / Rule |
|---|---|
| Authentication header | `X-API-Key` (mandatory) |
| Authentication error | `401` + `API_KEY_MISSING` / `API_KEY_INVALID` |
| Tracing identifier | `X-Request-Id` (optional) |
| Session / Cookie | none (stateless) |
| CSRF | irrelevant (service-to-service) |
| RBAC source | the upstream Tavanir system (caller) |