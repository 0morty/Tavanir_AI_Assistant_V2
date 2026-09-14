# Technical Document: Word-Boundary Binary Search Truncation

**Title:** Deterministic truncation algorithm with no text alteration using binary search on word boundaries

**Use case:** Context management, RAG systems, prompt building, and controlling the LLM input token budget

**Version:** 1.0.0

---

## 1. Purpose and Requirements

The goal of this algorithm is to truncate an input text to at most $N$ tokens such that the following technical requirements are guaranteed 100%:

1. **Exact Substring (full text originality):** The output must be a direct, untouched prefix of the original text (`text[0:k]`). No decoding, reconstruction, normalization, or alteration of whitespace is allowed.
2. **Hard Bound Constraint:** The number of output tokens must never exceed $N$ under any circumstances ($\text{TokenCount}(\text{Result}) \le N$).
3. **Word-Boundary Safety:** To avoid breaking characters or words mid-way, the cutoff point must always lie on the end boundary of a word.
4. **Zero Accumulated Error:** Unlike isolated chunking, token accounting is performed directly on the continuous prefix so that no BPE or space merge errors occur at boundaries.
5. **Tokenizer Independence:** The algorithm operates fully independently of the tokenizer type (Tiktoken, HuggingFace Fast Tokenizer, SentencePiece).

---

## 2. Algorithm Description

This algorithm uses **Binary Search over an array of word end indices**:

```
[original text]
   │
   ▼
[word boundary extraction] ──► extract the end index of each word with pattern (\S+\s*)
   │
   ▼
[binary search] ──────────────► low = 0 , high = len(words) - 1
   │
   ├─► mid = (low + high) // 2
   ├─► cutoff = words[mid]
   ├─► current_tokens = count_tokens(text[0:cutoff])
   │
   ├─► if current_tokens <= N ──► low = mid + 1  (advance to fill capacity)
   └─► if current_tokens > N  ──► high = mid - 1 (overflow; step back)
   │
   ▼
[deterministic output] ────────► text[0:best_cutoff]

```

### Word extraction pattern ($\texttt{\textbackslash S+\textbackslash s*}$)

* `\S+`: one or more non-space characters (the word itself).
* `\s*`: all spaces, tabs, or newlines immediately following the word.

This pattern guarantees that slicing up to the end of each word also captures all its trailing whitespace, leaving no dangling space at the beginning of the next chunk.

---

## 3. Complexity Analysis

* **Space Complexity:** $O(W)$, where $W$ is the number of words in the text (to store the word end indices).
* **Time Complexity:** $O(\log_2 W \cdot T_{\text{encode}})$
* For a 10,000-word text, the binary loop runs at most 14 times ($\log_2(10000) \approx 13.2$).
* Thanks to Fast Tokenizers (Rust-based), each `encode` call takes under 1 ms, and the entire truncation process completes in less than 3–5 ms.

---

## 4. Reference Code (Production-Ready Python)

```python
import re
from typing import Callable, List

def binary_search_truncate(
    text: str,
    max_tokens: int,
    token_count_fn: Callable[[str], int]
) -> str:
    """
    Truncates text to at most max_tokens using Binary Search over Word Boundaries.
    Guarantees 100% exact substring without any text mutation or normalization.

    :param text: original input text
    :param max_tokens: maximum number of allowed tokens (N)
    :param token_count_fn: function that takes a string and returns its token count
    :return: an exact slice of the original text
    """
    if not text or max_tokens <= 0:
        return ""

    # Extract the end indices of all words (including trailing whitespace)
    word_end_indices: List[int] = [m.end() for m in re.finditer(r'\S+\s*', text)]

    if not word_end_indices:
        return ""

    # Early check: if the whole text fits within capacity
    if token_count_fn(text) <= max_tokens:
        return text

    low = 0
    high = len(word_end_indices) - 1
    best_char_cutoff = 0

    while low <= high:
        mid = (low + high) // 2
        char_cutoff = word_end_indices[mid]

        # Evaluate the entire prefix exactly, from index 0 to the current boundary
        current_prefix = text[:char_cutoff]
        current_tokens = token_count_fn(current_prefix)

        if current_tokens <= max_tokens:
            best_char_cutoff = char_cutoff
            low = mid + 1  # try to fill more capacity
        else:
            high = mid - 1  # overflow occurred; move left

    return text[:best_char_cutoff]

```

---

## 5. Key Implementation Notes and Tokenizer Settings

| Setting | Suggested value | Reason |
| --- | --- | --- |
| `add_special_tokens` | `False` | Prevents adding system tokens such as `<s>` or `</s>` |
| `use_fast` | `True` | Uses the Rust implementation for maximum speed of the `encode` call |
| `return_tensors` | `None` | Avoids converting output into PyTorch/TensorFlow tensors to reduce memory-allocation overhead |

---

## 6. Comparison with Other Approaches

| Criterion | `encode -> slice -> decode` | Isolated Chunking | **Binary Search (this document)** |
| --- | --- | --- | --- |
| **Output originality (Exact Substring)** | ❌ No (risk of Unicode/Space changes) | ⚠️ Moderate | **100% deterministic** |
| **Token/word boundary alignment** | 100% on token | ⚠️ Suffers from boundary errors | **100% on word/token boundary** |
| **Overflow safety** | 100% | ❌ Risk of accumulated errors | **100% guaranteed** |
| **Code complexity** | Very simple | Complex (requires cluster management) | **Simple and maintainable** |

---

## Related documents

- [Overflow Strategies](overflow_strategies.md) — the `TRUNCATE` overflow strategy that this algorithm implements.