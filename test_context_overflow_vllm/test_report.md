# Real-vLLM Batch End-to-End Test Report

## A. Input

- vLLM base URL: `http://localhost:8000/v1` (reachable: `True`)
- Served model: `/models/LLM`
- Tokenizer: local `Qwen2.5-0.5B-Instruct/tokenizer.json` (`RawTokenizerAdapter` over the `tokenizers` crate)
- LLM temperature: `0.2` | LLM_MAX_TOKENS: `1024` | LLM timeout: `{timeout}s`
- vLLM serving config: `max_model_len=4096``

Per-chunk budgets (from `budget_probe.py`): `{'chunk-1': 300, 'chunk-2': 460, 'chunk-3': 510}`; strategies: chunk-1 `TRUNCATE`, chunk-2 `SUMMARIZE`, chunk-3 `[IGNORE, TRUNCATE]` (expects **no** overflow / full pass-through).

### chunk-1

Original chunk tokens: `433`

<details><summary>Original chunk text</summary>

The concept of context management in large language models represents one of the most significant engineering challenges in modern AI systems. When processing lengthy documents, the context window becomes a finite resource that must be allocated carefully among different pieces of information. This allocation process requires balancing multiple competing priorities, including preserving critical details, maintaining coherence, and ensuring that the most relevant information remains accessible throughout the generation process.

In practical applications, context overflow occurs when the combined size of all input sections exceeds the model's maximum token capacity. Rather than simply truncating from the end, sophisticated systems employ multiple strategies to reduce the footprint of content while attempting to preserve its semantic value. These strategies include direct truncation, summarization, and selective omission of lower-priority content. The choice of strategy often depends on the importance of the content, its compressibility, and the specific requirements of the task at hand.

The implementation of overflow handling requires careful coordination between several architectural components. A tokenization layer provides accurate token counts and, in advanced cases, offset mappings that allow for precise truncation without cutting words in the middle. A capacity allocator determines how much space each section should receive based on its stated demand and importance. A dispatcher routes overflow events to the appropriate reduction strategy for each compressible section. Finally, a context builder orchestrates the entire pipeline, ensuring that the final assembled prompt respects all budget constraints.

From a software engineering perspective, the use of dependency injection plays a crucial role in making these components testable and replaceable. By programming against abstractions rather than concrete implementations, the system can swap in mock tokenizers for unit tests or different LLM providers for production deployments. This flexibility is especially important in research and experimentation contexts, where requirements may evolve rapidly as new models and techniques emerge.

The end goal of these mechanisms is not merely to fit content within a token limit, but to do so in a way that maximizes the utility of the final prompt. This means preserving factual accuracy, maintaining logical structure, and retaining the specific details that will be most useful for the model's task. Achieving this balance requires both algorithmic sophistication and domain-specific tuning to match the characteristics of the content being processed.

</details>

### chunk-2

Original chunk tokens: `447`

<details><summary>Original chunk text</summary>

The field of natural language processing has witnessed remarkable progress in recent years, driven largely by the development of transformer-based architectures and the availability of large-scale training datasets. These models have demonstrated unprecedented capabilities in understanding and generating human language, enabling applications that range from automated translation to complex reasoning tasks. However, these capabilities come with inherent limitations, particularly regarding the fixed context window size that constrains how much information a model can consider at once.

One of the core challenges in working with limited context is determining which information is most relevant to preserve. Not all text carries equal weight for a given task; some passages contain essential facts, others provide supporting context, and still others may be redundant or tangential. Effective context management systems must therefore incorporate mechanisms to assess the relative importance of different sections and allocate resources accordingly. This often involves explicit importance scores, as well as structural cues about the role each section plays in the overall prompt.

Summarization emerges as a powerful tool for addressing context constraints. Rather than discarding content entirely, summarization attempts to distill the core meaning into a more compact form. Modern summarization approaches can be extractive, selecting key sentences from the original text, or abstractive, generating new text that captures the essence. When powered by the same class of language models, abstractive summarization can be particularly effective at condensing information while preserving coherence and nuance.

The trade-offs involved in context compression are multifaceted. Aggressive compression may save tokens but risk losing critical details or introducing subtle distortions. Conservative approaches preserve fidelity but may not free up enough space for other important content. The ideal strategy depends on the specific use case, the nature of the content, and the downstream task requirements. In many cases, a graduated approach that tries less destructive strategies first and falls back to more aggressive ones is preferable.

As models continue to evolve, the specific mechanics of context handling may change, but the underlying principles remain relevant. Token-based budgeting, importance-weighted allocation, and strategy-driven overflow handling represent general patterns that can be adapted to different architectures and constraints. By building these mechanisms as modular, injectable components, systems can evolve alongside the rapidly changing landscape of language model capabilities without requiring wholesale architectural rewrites.

</details>

### chunk-3

Original chunk tokens: `407`

<details><summary>Original chunk text</summary>

Organizations adopting large language model technology must carefully consider how to integrate these systems into their existing workflows while managing practical constraints. One of the most immediate operational concerns is the cost and latency associated with API calls, particularly when dealing with large contexts or high request volumes. Efficient context management directly impacts both of these factors by reducing token consumption and, in many cases, improving response times.

From an operational standpoint, batch processing presents an attractive optimization opportunity. Instead of sending requests sequentially, systems can group related requests together and submit them as a batch. This approach can improve throughput and reduce overhead when the underlying inference service supports batch endpoints. However, batch processing also introduces complexity in terms of error handling, result ordering, and resource allocation, all of which must be managed carefully.

Reliability is another critical consideration in production environments. Network issues, rate limiting, and temporary service unavailability are all realities that systems must handle gracefully. Robust implementations incorporate retry logic, proper error classification, and clear propagation of errors to calling code. By distinguishing between different types of failures, such as authentication errors, connection issues, and API errors, the system can take appropriate recovery actions and provide meaningful feedback to users.

The design of interfaces and abstractions plays a key role in operational flexibility. A well-defined port for LLM clients allows the same application logic to work with different providers, whether it's a self-hosted vLLM instance for cost control or a managed API service for convenience. This abstraction also facilitates testing, as dependencies can be replaced with fakes or mocks in non-production environments without affecting the core business logic.

Ultimately, the success of LLM integration depends on striking the right balance between technical sophistication and practical maintainability. While advanced context management techniques can improve model performance, they must be implemented in a way that is understandable, testable, and observable in production. Clear separation of concerns, dependency injection, and comprehensive error handling all contribute to building systems that can be operated reliably at scale while remaining adaptable to future changes in the rapidly evolving AI landscape.

</details>

## B. ContextBuilder processing (independent, real allocation + overflow)

### chunk-1

| Section budget | requested | capacity | overflowed | fitted |
|---|---|---|---|---|
| ROLE | 20 | 20 | False | 20 |
| HISTORY | 0 | 0 | False | 0 |
| CHUNKS | 442 | 217 | True | 217 |
| SYSTEM-INPUT | 19 | 19 | False | 19 |
| USER-INPUT | 25 | 25 | False | 25 |
| OUTPUT-FORMAT | 14 | 14 | False | 14 |

- Strategy applied: **TRUNCATE**

<details><summary>Fitted content actually placed in the prompt (strategy: TRUNCATE)</summary>

Chunk 1:
The concept of context management in large language models represents one of the most significant engineering challenges in modern AI systems. When processing lengthy documents, the context window becomes a finite resource that must be allocated carefully among different pieces of information. This allocation process requires balancing multiple competing priorities, including preserving critical details, maintaining coherence, and ensuring that the most relevant information remains accessible throughout the generation process.

In practical applications, context overflow occurs when the combined size of all input sections exceeds the model's maximum token capacity. Rather than simply truncating from the end, sophisticated systems employ multiple strategies to reduce the footprint of content while attempting to preserve its semantic value. These strategies include direct truncation, summarization, and selective omission of lower-priority content. The choice of strategy often depends on the importance of the content, its compressibility, and the specific requirements of the task at hand.

The implementation of overflow handling requires careful coordination between several architectural components. A tokenization layer provides accurate token counts and, in advanced cases, offset mappings that allow for precise truncation without cutting words in the

</details>

### chunk-2

| Section budget | requested | capacity | overflowed | fitted |
|---|---|---|---|---|
| ROLE | 20 | 20 | False | 20 |
| HISTORY | 0 | 0 | False | 0 |
| CHUNKS | 456 | 377 | True | 328 |
| SYSTEM-INPUT | 19 | 19 | False | 19 |
| USER-INPUT | 25 | 25 | False | 25 |
| OUTPUT-FORMAT | 14 | 14 | False | 14 |

- Strategy applied: **SUMMARIZE (real LLM summary used)**
- Summarization used the **real vLLM** through the same client (recorded as a separate 1-item batch call, see D/F).

<details><summary>Fitted content actually placed in the prompt (strategy: SUMMARIZE (real LLM summary used))</summary>

Natural Language Processing (NLP) has seen significant advancements over the past few decades, primarily due to the development of Transformer-based architectures and the availability of large-scale training datasets. These models excel in understanding and generating human language, enabling various applications such as automated translation and complex reasoning tasks. Despite their impressive capabilities, NLP also faces limitations related to the fixed context window size, which restricts how much information a model can consider simultaneously.

Effective context management systems must address the issue of determining the relevance of different sections within a given task. Different types of texts carry varying degrees of importance, with some containing crucial facts, others providing supporting context, and others potentially being redundant or tangential. To manage these contexts effectively, summarization techniques can be employed. Extractive summarization selects key sentences from the original text, while abstractive summarization generates new text that encapsulates the main points while maintaining coherence and nuance.

Context compression is a challenging task that requires balancing token savings against the loss of critical information or the introduction of subtle distortions. Gradual approaches, starting with less destructive strategies and then moving to more aggressive ones, offer an optimal solution. Modularity and injectability of these mechanisms ensure that system evolution remains compatible with evolving language model capabilities.

As NLP continues to advance, the specific mechanics of context handling will likely change, but the fundamental principles remain relevant. Token-based budgeting, importance-weighted allocation, and strategy-driven overflow handling are general patterns that can be adapted across different architectures and constraints. By incorporating these mechanisms as modular, injectable components, systems can adapt to evolving NLP landscapes without requiring extensive architectural changes.

</details>

### chunk-3

| Section budget | requested | capacity | overflowed | fitted |
|---|---|---|---|---|
| ROLE | 20 | 20 | False | 20 |
| HISTORY | 0 | 0 | False | 0 |
| CHUNKS | 416 | 416 | False | 416 |
| SYSTEM-INPUT | 19 | 19 | False | 19 |
| USER-INPUT | 25 | 25 | False | 25 |
| OUTPUT-FORMAT | 14 | 14 | False | 14 |

- Strategy applied: **none (content passes through unchanged)**

<details><summary>Fitted content actually placed in the prompt (strategy: none (content passes through unchanged))</summary>

Relevant context chunks:

Chunk 1:
Organizations adopting large language model technology must carefully consider how to integrate these systems into their existing workflows while managing practical constraints. One of the most immediate operational concerns is the cost and latency associated with API calls, particularly when dealing with large contexts or high request volumes. Efficient context management directly impacts both of these factors by reducing token consumption and, in many cases, improving response times.

From an operational standpoint, batch processing presents an attractive optimization opportunity. Instead of sending requests sequentially, systems can group related requests together and submit them as a batch. This approach can improve throughput and reduce overhead when the underlying inference service supports batch endpoints. However, batch processing also introduces complexity in terms of error handling, result ordering, and resource allocation, all of which must be managed carefully.

Reliability is another critical consideration in production environments. Network issues, rate limiting, and temporary service unavailability are all realities that systems must handle gracefully. Robust implementations incorporate retry logic, proper error classification, and clear propagation of errors to calling code. By distinguishing between different types of failures, such as authentication errors, connection issues, and API errors, the system can take appropriate recovery actions and provide meaningful feedback to users.

The design of interfaces and abstractions plays a key role in operational flexibility. A well-defined port for LLM clients allows the same application logic to work with different providers, whether it's a self-hosted vLLM instance for cost control or a managed API service for convenience. This abstraction also facilitates testing, as dependencies can be replaced with fakes or mocks in non-production environments without affecting the core business logic.

Ultimately, the success of LLM integration depends on striking the right balance between technical sophistication and practical maintainability. While advanced context management techniques can improve model performance, they must be implemented in a way that is understandable, testable, and observable in production. Clear separation of concerns, dependency injection, and comprehensive error handling all contribute to building systems that can be operated reliably at scale while remaining adaptable to future changes in the rapidly evolving AI landscape.

</details>

## C. Batch construction (chunk -> prompt -> batch index mapping)

Each `ContextBuilderResult.prompt` becomes exactly one user message. Prompts are collected in fixed order `chunk-1, chunk-2, chunk-3` and submitted through **one** `OpenAILLMClient.complete_many(prompts)` call (vLLM `POST /v1/chat/completions/batch`). The batch message index equals the body's position for each chunk:

| batch index | chunk | prompt tokens |
|---|---|---|
| 0 | chunk-1 | 296 |
| 1 | chunk-2 | 406 |
| 2 | chunk-3 | 494 |

<details><summary>Constructed batch body (what the pipeline intends to send)</summary>

```json
{
  "model": "/models/LLM",
  "messages": [
    [
      {
        "role": "user",
        "content": "You are a meticulous technical analyst. Use the provided context chunks to answer the user's question accurately.\n\nChunk 1:\nThe concept of context management in large language models represents one of the most significant engineering challenges in modern AI systems. When processing lengthy documents, the context window becomes a finite resource that must be allocated carefully among different pieces of information. This allocation process requires balancing multiple competing priorities, including preserving critical details, maintaining coherence, and ensuring that the most relevant information remains accessible throughout the generation process.\n\nIn practical applications, context overflow occurs when the combined size of all input sections exceeds the model's maximum token capacity. Rather than simply truncating from the end, sophisticated systems employ multiple strategies to reduce the footprint of content while attempting to preserve its semantic value. These strategies include direct truncation, summarization, and selective omission of lower-priority content. The choice of strategy often depends on the importance of the content, its compressibility, and the specific requirements of the task at hand.\n\nThe implementation of overflow handling requires careful coordination between several architectural components. A tokenization layer provides accurate token counts and, in advanced cases, offset mappings that allow for precise truncation without cutting words in the\n\nAnswer the user's question strictly based on the context chunks provided above. Do not invent facts.\n\nWhat is the single most important takeaway of the material above? Answer in one short sentence (at most 30 words).\n\nPlain text only. No preamble, no bullets, no markdown headers."
      }
    ],
    [
      {
        "role": "user",
        "content": "You are a meticulous technical analyst. Use the provided context chunks to answer the user's question accurately.\n\nNatural Language Processing (NLP) has seen significant advancements over the past few decades, primarily due to the development of Transformer-based architectures and the availability of large-scale training datasets. These models excel in understanding and generating human language, enabling various applications such as automated translation and complex reasoning tasks. Despite their impressive capabilities, NLP also faces limitations related to the fixed context window size, which restricts how much information a model can consider simultaneously.\n\nEffective context management systems must address the issue of determining the relevance of different sections within a given task. Different types of texts carry varying degrees of importance, with some containing crucial facts, others providing supporting context, and others potentially being redundant or tangential. To manage these contexts effectively, summarization techniques can be employed. Extractive summarization selects key sentences from the original text, while abstractive summarization generates new text that encapsulates the main points while maintaining coherence and nuance.\n\nContext compression is a challenging task that requires balancing token savings against the loss of critical information or the introduction of subtle distortions. Gradual approaches, starting with less destructive strategies and then moving to more aggressive ones, offer an optimal solution. Modularity and injectability of these mechanisms ensure that system evolution remains compatible with evolving language model capabilities.\n\nAs NLP continues to advance, the specific mechanics of context handling will likely change, but the fundamental principles remain relevant. Token-based budgeting, importance-weighted allocation, and strategy-driven overflow handling are general patterns that can be adapted across different architectures and constraints. By incorporating these mechanisms as modular, injectable components, systems can adapt to evolving NLP landscapes without requiring extensive architectural changes.\n\nAnswer the user's question strictly based on the context chunks provided above. Do not invent facts.\n\nWhat is the single most important takeaway of the material above? Answer in one short sentence (at most 30 words).\n\nPlain text only. No preamble, no bullets, no markdown headers."
      }
    ],
    [
      {
        "role": "user",
        "content": "You are a meticulous technical analyst. Use the provided context chunks to answer the user's question accurately.\n\nRelevant context chunks:\n\nChunk 1:\nOrganizations adopting large language model technology must carefully consider how to integrate these systems into their existing workflows while managing practical constraints. One of the most immediate operational concerns is the cost and latency associated with API calls, particularly when dealing with large contexts or high request volumes. Efficient context management directly impacts both of these factors by reducing token consumption and, in many cases, improving response times.\n\nFrom an operational standpoint, batch processing presents an attractive optimization opportunity. Instead of sending requests sequentially, systems can group related requests together and submit them as a batch. This approach can improve throughput and reduce overhead when the underlying inference service supports batch endpoints. However, batch processing also introduces complexity in terms of error handling, result ordering, and resource allocation, all of which must be managed carefully.\n\nReliability is another critical consideration in production environments. Network issues, rate limiting, and temporary service unavailability are all realities that systems must handle gracefully. Robust implementations incorporate retry logic, proper error classification, and clear propagation of errors to calling code. By distinguishing between different types of failures, such as authentication errors, connection issues, and API errors, the system can take appropriate recovery actions and provide meaningful feedback to users.\n\nThe design of interfaces and abstractions plays a key role in operational flexibility. A well-defined port for LLM clients allows the same application logic to work with different providers, whether it's a self-hosted vLLM instance for cost control or a managed API service for convenience. This abstraction also facilitates testing, as dependencies can be replaced with fakes or mocks in non-production environments without affecting the core business logic.\n\nUltimately, the success of LLM integration depends on striking the right balance between technical sophistication and practical maintainability. While advanced context management techniques can improve model performance, they must be implemented in a way that is understandable, testable, and observable in production. Clear separation of concerns, dependency injection, and comprehensive error handling all contribute to building systems that can be operated reliably at scale while remaining adaptable to future changes in the rapidly evolving AI landscape.\n\nAnswer the user's question strictly based on the context chunks provided above. Do not invent facts.\n\nWhat is the single most important takeaway of the material above? Answer in one short sentence (at most 30 words).\n\nPlain text only. No preamble, no bullets, no markdown headers."
      }
    ]
  ],
  "temperature": 0.2,
  "max_tokens": 1024
}
```

</details>

## D. Actual HTTP payload captured at the wire level

### Batch POST call #1: `/chat/completions/batch`  (elapsed `145.318s`, items `1`)

`messages` array (one conversation per item, first ~120 chars each):

- item 0 (`chunk-2 (summarization prompt)`): `You are a text summarization expert. You summarize the given text separately and faithfully, preserving its core content...` (3237 chars)

Per-choice result (index / finish_reason / content length):

- index `0`: finish_reason=`stop`, content chars `2076`

### Batch POST call #2: `/chat/completions/batch`  (elapsed `69.505s`, items `3`)

`messages` array (one conversation per item, first ~120 chars each):

- item 0 (`chunk-1`): `You are a meticulous technical analyst. Use the provided context chunks to answer the user's question accurately.

Chunk...` (1776 chars)
- item 1 (`chunk-2`): `You are a meticulous technical analyst. Use the provided context chunks to answer the user's question accurately.

Natur...` (2473 chars)
- item 2 (`chunk-3`): `You are a meticulous technical analyst. Use the provided context chunks to answer the user's question accurately.

Relev...` (2977 chars)

Per-choice result (index / finish_reason / content length):

- index `0`: finish_reason=`stop`, content chars `260`
- index `1`: finish_reason=`stop`, content chars `301`
- index `2`: finish_reason=`stop`, content chars `172`

## E. Actual model responses (real vLLM) and index mapping

The batch response carries one choice per conversation, indexed `0..N-1`. `OpenAILLMClient._extract_batch_results` maps each choice back by its `index`, preserving input order:

| batch index | chunk | finish_reason | response (first 200 chars) |
|---|---|---|---|
| 0 | chunk-1 | `stop` | The single most important takeaway is the complex challenge of managing context in large language models, which involves allocating resources efficiently while balancing various priorities such as pre |
| 1 | chunk-2 | `stop` | The single most important takeaway is the need for effective context management systems to handle the complexities of NLP, including summarization, extraction, and context compression, ensuring that a |
| 2 | chunk-3 | `stop` | The single most important takeaway from the material is the importance of efficient context management and reliability in integrating large language models into operations. |

## F. Request counts (batch architecture proof)

| metric | count |
|---|---|
| ContextBuilder processing calls | `3` (one per chunk) |
| `complete_many` (batch POST) HTTP calls | `2` |
| `complete` / `chat.completions.create` fallback calls | `0` |
| total batch POST items | `4` (1 summarization + 1 final batch of 3) |
| final batch items | `3` |
| independent final generations via separate `complete()` calls | `0` |

Assertions that must hold for the batch objective:

- [ ] exactly one final batch POST with **3** items
- [ ] final batch message order `chunk-1, chunk-2, chunk-3` matches batch indexes `0, 1, 2`
- [ ] zero individual `complete()` calls for the final generation (no fallback to concurrent `create`)
- [ ] three independent responses returned in input order

## G. Hard-cut verification (no artificial truncation)

The `SUMMARIZE` strategy's summary length is bounded by `LLM_MAX_TOKENS` (the real request `max_tokens`), NOT by the ContextBuilder capacity. This section proves the environment is sized so nothing is cut off:

| item | value |
|---|---|
| vLLM `max_model_len` | `4096` |
| `LLM_MAX_TOKENS` (request `max_tokens`) | `1024` |

| summarization input tokens (ChunkPromptBuilder, chunk-2) | `535` |
| summarization request headroom (input + max_tokens) | `1559` <= 4096? `True` |
| summarization output tokens | `328` |
| largest final prompt tokens | `494` |
| final batch request headroom (max prompt + max_tokens) | `1518` <= 4096? `True` |

finish_reason per real generation:

- POST #1 index `0` -> finish_reason `stop`
- POST #2 index `0` -> finish_reason `stop`
- POST #2 index `1` -> finish_reason `stop`
- POST #2 index `2` -> finish_reason `stop`

- **all generations finish_reason == `stop`? `True`** (if `length`, LLM_MAX_TOKENS is the hard cut and must be raised)

## H. Deviations / limitations

- Production DI (`src.containers.py`) is untouched; this test composes the real classes directly with a `tokenizers`-crate adapter in place of the `transformers`-based GemmaTokenizer (identical BPE counts).
- The AsyncOpenAI instance is wrapped at the `post`/`create` seam (test-only, reverted on process end) to capture the true HTTP traffic.
- No mock or fake LLM is used for generation; SUMMARIZE and the final batch both hit the real vLLM model.
