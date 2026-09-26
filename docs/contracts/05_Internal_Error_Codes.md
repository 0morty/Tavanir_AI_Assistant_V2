# Internal Error Code Dictionary for Tavanir AI Assistant V2

To manage errors uniformly between the upstream Tavanir system (caller) and the **Tavanir AI Assistant V2** service, a set of internal error codes (`INTERNAL_CODE`) is defined. These codes are used consistently in API responses so the caller can identify the error type without parsing message text.

> **Grounded in code:** many codes map 1:1 to exceptions defined in `src/application/exceptions.py` and `src/domain/exceptions.py`. Where a code is not yet implemented, it is marked **[planned]**.

## INTERNAL_CODE Characteristics

- Always `SCREAMING_SNAKE_CASE`
- No spaces, no dots
- Short, meaningful, and unique

## Caller's Role in Code Handling

Based on `INTERNAL_CODE`, the caller should:
- display an appropriate message to the end user,
- translate the message per the user's language (i18n),
- execute specific behavior (e.g. receiving `EMBEDDER_CONNECTION_FAILED` → show "embedding service unavailable").

## Suggested: Error Mapper Layer

To avoid scattered logic, an **Error Mapper** layer on the caller side is suggested, converting `INTERNAL_CODE` into user-displayable, multi-language messages.

## Keeping the Table Updated

Whenever a new capability is added or a new error scenario is defined:
- add the new code,
- complete its description,
- review or remove old codes as needed.

---

## Internal Codes Table

| code | http_status | mapped exception | description |
|---|---|---|---|
| `UNAUTHORIZED` | 401 | — | no/invalid token or credential sent |
| `API_KEY_MISSING` | 401 | — | the `X-API-Key` header was not sent |
| `API_KEY_INVALID` | 401 | — | the API key value is invalid |
| `FORBIDDEN` | 403 | — | no access permission for this operation |
| `VALIDATION_ERROR` | 422 | — | general input validation error |
| `MISSING_REQUIRED_FIELD` | 422 | — | a required field was not provided |
| `PAYLOAD_MISMATCH` | 400 | — | array item counts do not match (e.g. suggestionIds ≠ items) |
| `INVALID_SUGGESTION_STATUS` | 422 | `InvalidSuggestionStatusError` | status string/id is not a known `SuggestionStatus` |
| `INVALID_SHAMSI_DATE` | 422 | `InvalidShamsiDateFormatError` | date does not match `YYYY/MM/DD` |
| `SUGGESTION_NOT_FOUND` | 404 | — | suggestion with the given id was not found |
| `SUGGESTION_ALREADY_INGESTED` | 409 | — | suggestion with this id is already indexed (use update) |
| `SUGGESTION_IN_PROCESSING` | 409 | — | suggestion is being processed; delete/update not allowed |
| `SUGGESTION_INVALID_STATE` | 400 | — | suggestion is in an invalid state for this operation |
| `TEMPLATE_INVALID` | 422 | — | the custom prompt template failed validation |
| `EMBEDDING_FAILED` | 500 | `EmbedderAPIError` | error producing vectors (provider API error) |
| `EMBEDDER_CONNECTION_FAILED` | 503 | `EmbedderConnectionError` | network/timeout communicating with the embedder provider |
| `EMBEDDER_AUTH_FAILED` | 401 | `EmbedderAuthenticationError` | embedder provider authentication failed |
| `EMBEDDER_CONTEXT_LENGTH` | 422 | `EmbedderContextLengthError` | text exceeds the model's context window (truncate disabled) |
| `LLM_CONFIGURATION_ERROR` | 500 | `LLMConfigurationError` | provider config/API key missing or invalid |
| `LLM_CONNECTION_FAILED` | 503 | `LLMConnectionError` | network/timeout communicating with the LLM provider |
| `LLM_API_ERROR` | 502 | `LLMAPIError` | the LLM provider returned an API error |
| `LLM_AUTH_FAILED` | 401 | `LLMAuthenticationError` | LLM provider authentication failed |
| `PROMPT_BUDGET_EXCEEDED` | 422 | `PromptBudgetExceededError` | fixed prompt sections (system instruction, user query, output format) exceed token budget |
| `INSUFFICIENT_EVIDENCE_BUDGET` | 422 | `InsufficientEvidenceBudgetError` | remaining token capacity cannot fit even the highest-ranked similar suggestion |
| `INVALID_SUGGESTION_CONTENT` | 422 | `InvalidSuggestionContentError` | suggestion title, problem, or solution is empty or non-substantive |
| `DUPLICATE_EVIDENCE_ID` | 422 | `DuplicateEvidenceIdError` | duplicate similar suggestion ID detected in generation input |
| `RETRIEVAL_FAILED` | 500 | — | vector retrieval from Qdrant failed **[planned]** |
| `GENERATION_FAILED` | 500 | — | answer generation by the model failed |
| `MSSQL_EXTRACTION_FAILED` | 500 | — | error extracting suggestions from legacy MSSQL **[planned]** |
| `STATUTE_PARSE_FAILED` | 422 | — | error parsing an Excel statute file **[planned]** |
| `TEXT_NORMALIZATION_FAILED` | 422 | `TextNormalizationError` | Persian text cleaning or normalization failed |
| `CHUNKING_FAILED` | 422 | `ChunkingError` | error decomposing document into vector chunks |
| `RATE_LIMITED` | 429 | — | too many requests |
| `INTERNAL_ERROR` | 500 | `ApplicationError` | unexpected internal service error |
| `NOT_IMPLEMENTED` | 501 | — | this capability is not yet implemented |

---

> **Note:** End-user authentication codes (e.g. `OTP_INVALID`, `USER_BLOCKED`) are not defined in this service, because the V2 service has no user/auth layer — user and RBAC concerns belong to the upstream Tavanir system.