# Gemma Tokenizer Usage in the RAG ContextBuilder (Internal Engineering Reference)

**Status:** Reference material (no code changes)

**Sources used (official only):**

| Ref | Source |
|---|---|
| [D] | https://huggingface.co/docs/transformers/model_doc/gemma (transformers `v5.17.0`) |
| [S] | https://github.com/huggingface/transformers/blob/main/src/transformers/models/gemma/tokenization_gemma.py |

**Evidence labels used throughout:**
- `[D]` — directly documented behavior (Gemma docs page).
- `[S]` — directly readable in `tokenization_gemma.py` source.
- `[L]` — behavior of the Rust `tokenizers` / transformers libraries in general (not stated in the two Gemma sources, but implemented by the fast-tokenizer backend).
- `[A]` — our project's architecture/engineering decision, **not** HF-documented.

---

## 0. Scope note: "Gemma 4"

The two official sources above do **not** document a "Gemma 4" model or a "Gemma 4 Tokenizer":

- The docs page `model_doc/gemma` documents the original Gemma family (2B/7B checkpoints, e.g. `google/gemma-2b`) `[D]`.
- The tokenizer source lives at `src/transformers/models/gemma/tokenization_gemma.py` and defines the `GemmaTokenizer` used by the Gemma family `[S]`.

This document therefore describes the **Gemma tokenizer as officially documented**. If a future Gemma-family checkpoint ships with a tokenizer, the same integration points (fast BPE/byte-fallback backend, offset mapping) are expected to hold, but that expectation is **not** asserted from these sources.

---

## 1. `GemmaTokenizer` architecture and why to use it

### 1.1 It *is* the fast tokenizer

In current transformers, `GemmaTokenizer` is the **fast** tokenizer:

- The class docstring states: "Construct a **fast** Gemma tokenizer (backed by HuggingFace's tokenizers library)." `[D]`
- In source it is `class GemmaTokenizer(TokenizersBackend)` — the `TokenizersBackend` base class wraps the Rust `tokenizers` library. `[S]`
- `VOCAB_FILES_NAMES = {"tokenizer_file": "tokenizer.json"}` — the tokenizer is loaded from a serialized `tokenizer.json` produced by the Rust library. `[S]`

There is **no separate `GemmaTokenizerFast`** class in the current API; the fast backend is what `GemmaTokenizer` is. (Older transformers releases exposed a distinct `GemmaTokenizerFast`; the v5 API folds that into `GemmaTokenizer`.)

### 1.2 The tokenization pipeline (from source)

The Rust-backed pipeline configured in `tokenization_gemma.py` is: `[S]`

```
BPE (byte_fallback=True, fuse_unk=True)
  └─ pretokenizer: Split(pattern=" ", behavior="merged_with_previous")
  └─ normalizer:   Replace(" ", "▁")          # ASCII space → U+2581
  └─ decoder:      Sequence([Replace("▁", " "), ByteFallback(), Fuse()])
```

Key documented/source facts:

- **BPE model** with `byte_fallback=True` and `fuse_unk=True`. `[S]`
- **No prefix space** is added (unlike many BPE tokenizers). `[D]`
- The normalizer replaces **ASCII space** (U+0020) with `"▁"` (U+2581). `[D][S]`
- The pretokenizer splits on **`" "` only** (merged-with-previous behavior). `[S]`
- The decoder restores `▁` → space, then applies byte fallback and fusion. `[S]`
- `padding_side = "left"`, `model_input_names = ["input_ids", "attention_mask"]`. `[S]`

### 1.3 Why the fast backend should be used

- **Offset mapping**: reliable per-token `(start, end)` character offsets are a fast-tokenizer capability; slow Python tokenizers cannot provide them. This is required for exact-substring truncation (§6). `[L]`
- **Speed**: tokenization is executed in the Rust layer; re-encoding prefixes during binary-search truncation becomes cheap.
- **Determinism**: the same serialized `tokenizer.json` yields identical tokenization across runs and processes. `[S]` (the fast backend consumes the serialized file directly).

---

## 2. Correct initialization with `from_pretrained`

Use the tokenizer-loading API exactly as the official docs show — it is a **model-loading step** and must resolve `tokenizer.json` from the checkpoint: `[D]`

```python
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("google/gemma-2b")
```

`AutoTokenizer.from_pretrained("google/gemma-2b")` returns the fast `GemmaTokenizer` for the checkpoint. `[D]` The equivalent class-bound form is `GemmaTokenizer.from_pretrained(...)`; because the file defined in `VOCAB_FILES_NAMES` is `tokenizer.json`, loading reads the serialized fast tokenizer. `[S]`

Required when loading: the `transformers` package installed with the Rust tokenizers dependency (the fast backend). The checkpoint path is a Hub repo id or a local directory. `[D]`

---

## 3. Why loading must happen outside our adapter (constructor injection)

This is an **architecture decision** of our codebase (`[A]`), not a HF-documented requirement:

```
Application Tokenizer Interface (src/domain/context/tokenizer.py)
        │
        v
GemmaTokenizer Adapter (src/infrastructure/services/tokenizers/gemma_tokenizer.py)
        │
        v
GemmaTokenizerFast / GemmaTokenizer (Hugging Face, created externally)
```

- The adapter's constructor receives an **already-created** HF tokenizer instance and stores it as a private attribute.
- The adapter **never calls** `AutoTokenizer.from_pretrained(...)` / `GemmaTokenizer.from_pretrained(...)` and never downloads anything.

Rationale (engineering, not HF-documented):

1. **Single instance / connection reuse** — loading is done once at composition root and injected everywhere, instead of per-call.
2. **Startup isolation** — importing the adapter module must not trigger network I/O or model downloads.
3. **Testability** — a fake/stand-in tokenizer can be injected in unit tests without `transformers` installed.
4. **Layer separation** — the domain abstraction stays pure stdlib; the concrete adapter stays a thin translation layer.

---

## 4. Token counting, `add_special_tokens`, BOS/EOS

### 4.1 Special tokens (documented)

Special-token defaults from the docs/source: `[D][S]`

| Token | String | ID (GemmaConfig) |
|---|---|---|
| `pad_token` | `<pad>` | `0` |
| `eos_token` | `<eos>` | `1` |
| `bos_token` | `<bos>` | `2` |
| `unk_token` | `<unk>` | `3` |
| `mask_token` | `<mask>` | `4` |

`GemmaConfig` documents `bos_token_id=2`, `eos_token_id=1`, `pad_token_id=0`. `[D]`

### 4.2 Whether special tokens are added

The tokenizer has two configuration flags: `[D]`

- `add_bos_token: bool = True` — "Whether or not to add a `bos_token` at the start of sequences."
- `add_eos_token: bool = False` — "Whether or not to add an `eos_token` at the end of sequences."

**Consequences for counting:**

- By **default**, every call that tokenizes a text starts with a `<bos>` token, and does **not** end with `<eos>`.
- A typical single text therefore tokenizes as `[<bos>, ...content tokens...]`; the BOS counts toward the token budget.
- The generic transformers `add_special_tokens` parameter (on `__call__`/`encode`) can override this behavior per call. `[L]` (This flag itself is not described on the Gemma pages; it is part of the shared transformer tokenizer API.)
- Wrong-counting pitfall: `len(tokenizer)` returns the **vocabulary size** (256000 for Gemma), not the token count of a text. `[L]`

### 4.3 Counting in our adapter

Our `Tokenizer.count_tokens(text)` is implemented as `len(self._tokenizer.encode(text))` — i.e. it counts exactly the token IDs that `encode` produces, including the default BOS. This keeps `count_tokens` consistent with what will actually be sent to the LLM, at the cost of counting `<bos>`.

If a token budget should exclude special tokens, that is a per-call decision made *outside* the adapter (e.g. passing `add_special_tokens=False` in the HF call). It is a policy choice, not something the adapter decides.

---

## 5. How `return_offsets_mapping=True` works

- `return_offsets_mapping=True` is passed to a fast-tokenizer call, and the returned `offset_mapping` field contains, **for each token, a `(start, end)` pair of character offsets**. `[L]`
- This capability comes from the Rust `tokenizers` library and is generic fast-tokenizer functionality; it is **not** described on the Gemma pages or in `tokenization_gemma.py`. `[L]`
- For a single string input, offsets are per-token:

```python
encoding = tokenizer(text, return_offsets_mapping=True)
offsets = encoding["offset_mapping"]
# e.g. [ (0, 0), (0, 5), (6, 11), ... ]   -- first entry may be <bos> special token
```

- Special tokens (e.g. the default `<bos>`) are typically reported with an offset of `(0, 0)`. `[L]` Consumers must skip/ignore those entries.
- `padding_side = "left"` means padding tokens appear at the start of a padded `BatchEncoding` — a relevant detail if we ever batch inputs. `[S]`

**Our adapter** calls `self._tokenizer(text, return_offsets_mapping=True)` inside `encode` and returns each `(token_id, (start, end))` pair.

---

## 6. Do offsets refer to the original input, and how to use them for exact truncation

### 6.1 Yes, relative to the input string

In the fast-tokenizer backend, `offset_mapping` offsets are relative to the **original input string** passed by the caller (the text you passed in, not the normalized `"▁"`-replaced version). `[L]`

This means a `(start, end)` pair indexes directly into `text`, e.g. `text[start:end]` yields exactly the characters that generated that token.

### 6.2 Use for exact truncation

Truncation must produce a prefix of the original text (the requirement of the word-boundary binary-search document). Offsets give us the exact cut points:

```
text = "بررسی پیشنهاد... " (original user/retrieval text)
         │
         ▼
offsets = [o for _, o in encode(text)]       # token boundaries as (start, end)
         │
         ▼
choose k-th token end = offsets[k][1] such that:
    count_tokens(text[:offsets[k][1]]) <= capacity
         │
         ▼
result = text[:offsets[k][1]]         # byte-exact prefix of original input
```

- `text[:end]` is a guaranteed **exact substring** of the original input — no whitespace is added, removed, or replaced.
- Re-counting `text[:cut]` directly (not summing per-token counts) avoids accumulated BPE/space-merge errors. `[A]` (matches `word_boundary_binary_search_truncation.md`)

---

## 7. Why slicing by offsets is preferred over `decode()`

Two ways to turn a token prefix back into text:

| | Slice `text[:offset_end]` | `tokenizer.decode(token_ids)` |
|---|---|---|
| Exactness | Byte-exact substring of the user's input, by construction | Reconstructed text via the decoder pipeline |
| Whitespace | Preserved verbatim | `▁` is re-replaced by space; `ByteFallback()` + `Fuse()` transform the token stream `[S]` |
| Special tokens | Never appears (we slice the original) | Appears unless `skip_special_tokens=True` |
| Determinism | Deterministic | Depends on decode flags (`clean_up_tokenization_spaces`) |

The decoder configured for Gemma is `Sequence([Replace("▁", " "), ByteFallback(), Fuse()])` `[S]` — it is designed to *read nicely*, **not** to reproduce an exact substring. That is why `decode()` is unsuitable when the output must preserve the user's original content byte-for-byte (citation fidelity in RAG, answering from retrieved chunks). Slicing by offsets has no such transformation step.

**Rule:** for anything that must round-trip the user's text exactly, slice the original string using offsets; reserve `decode()` for display reconstruction.

---

## 8. Important edge cases

### 8.1 Spaces

- The normalizer replaces ASCII space with `▁` (U+2581) before encoding, and the decoder reverses it. `[S]`
- Offsets still refer to the **original** string, so `text[:end]` slicing is unaffected by the `▁` substitution. `[L]`
- Because slicing keeps the original, trailing spaces at a cut boundary are preserved as-is.

### 8.2 Newlines

- The pretokenizer splits on `" "` only; **newline is not a split pattern** in this tokenizer. `[S]`
- The normalizer only replaces `" "`, so newlines pass through unmodified. `[S]`
- Practical consequence: a newline is generally carried inside a produced token (via byte fallback) rather than being its own dedicated token. It is not a hard word boundary for the pretokenizer. `[S]`
- Offset mapping remains character-accurate regardless, so slicing still works across newlines. `[L]`

### 8.3 Persian text

- No Persian-specific normalization exists in this tokenizer; the **only** normalizer is `Replace(" ", "▁")`. `[S]`
- Persian characters (Arabic-script) are handled by the generic BPE with `byte_fallback=True`, i.e. unseen Unicode can be represented as byte-fallback tokens. `[S]`
- The space between Persian words is ASCII `U+0020`, so the same `▁` mechanism applies. `[S]`
- Conclusion: Persian throughput is byte-safe; exactness is guaranteed only when we **slice** by offsets, never when we rely on `decode()`.

### 8.4 نیمفاصله (ZWNJ, U+200C)

- نیمفاصله is **not** ASCII space, so the normalizer does **not** replace it. It stays in the stream and is encoded by BPE/byte fallback. `[S]`
- For Persian compound words (e.g. «میخواهم», «بههمراه»), ZWNJ is significant.
- Slicing by offsets preserves ZWNJ exactly. `[L]`
- A `decode()` round-trip may insert/remove adjacent spaces due to the `Fuse()`/`Replace("▁", " ")` decoder steps, so never use `decode()` when ZWNJ fidelity matters. `[S]`

---

## 9. Integration with our `Tokenizer` abstraction

Concrete mapping (`src/domain/context/tokenizer.py` ↔ `src/infrastructure/services/tokenizers/gemma_tokenizer.py`):

| Abstraction member | GemmaAdapter implementation | Notes |
|---|---|---|
| `supports_offset_mapping` (read-only property, no setter) | `return True` | Part of the interface contract; the flag documents that offsets are available (the fast backend provides them, `[L]`). |
| `encode(text) -> list[tuple[int, tuple[int,int]]]` | `self._tokenizer(text, return_offsets_mapping=True)` → `zip(ids, offset_mapping)` | Each element is `(token_id, (start, end))` **including default `<bos>`** (see §4.2); offsets are into the original string; skip `(0,0)` special-token entries before using cut indices (see §5, §6). |
| `count_tokens(text) -> int` | `len(self.encode(text))` | Counts exactly what `encode` produces; consistent with the budget sent to the LLM. |

Design rules that follow:

- The abstraction stays minimal and pure-stdlib; it never imports `transformers`. `[A]`
- The adapter is a thin translation layer; it contains **no** truncation, summarizing, or overflow logic. `[A]`
- Offsets are part of the `encode` contract; `supports_offset_mapping` remains a read-only indicator that every concrete adapter must expose, and current implementations return `True`. `[A]`
- BOS-inclusive counting is the current contract of `count_tokens`. If the token budget must exclude `<bos>`, the exclusion is applied at the call site (via `add_special_tokens=False`), not inside the adapter. `[L][A]`

---

## 10. References

- Gemma (transformers docs): https://huggingface.co/docs/transformers/model_doc/gemma
- `tokenization_gemma.py` (transformers main): https://github.com/huggingface/transformers/blob/main/src/transformers/models/gemma/tokenization_gemma.py
- Related internal docs: [Overflow Strategies](overflow_strategies.md), [Word-Boundary Binary Search Truncation](word_boundary_binary_search_truncation.md), [Prompt-Builder Architecture](prompt_builder_entities.md)