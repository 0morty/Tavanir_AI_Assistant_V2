# Section Properties: `importance` and `demand`

This document defines the two properties every `ISection` carries: **`importance`** and **`demand`**.
It is an architectural/domain reference for how these two concepts are meant to be understood and
used. It does **not** describe any token-allocation algorithm.

Both properties are relative weights in the range `[0.0, 1.0]`:

- Valid range: `[0.0, 1.0]`
- Values do **not** need to sum to `1.0` across Sections
- An `ISection` never normalizes them
- Neither property is a percentage of the context window

---

## `importance`

`importance` represents the **intrinsic semantic importance of a Section's information**.

> How important is the information contained in this Section?

Examples:

| Section | Relative importance |
|---|---|
| User Input | very high |
| Retrieved Chunks | high |
| History | medium |
| Output Format | relatively low |

### Rules

- `importance` is a relative weight in `[0.0, 1.0]`.
- It is **not** a percentage of the context window.
- `importance = 0.3` does **not** mean the Section may use 30% of the tokens.
- Importance values do not need to sum to `1.0`.
- The value describes semantic value and may serve future decision-making (e.g. prioritizing a
  Section) alike.

---

## `demand`

`demand` represents the Section's **relative inherent demand for context capacity**.

> Compared with other Sections, how much context space does this Section naturally require?

Examples:

| Section | Relative demand |
|---|---|
| Chunks | high — may contain many/large retrieved items |
| History | relatively high |
| User Input | low — the user's query is usually short |
| Output Format | very low |

### Rules

- `demand` is also a relative value in `[0.0, 1.0]`.
- It is **not itself a token percentage**.
- It does not need to sum to `1.0` with other Sections.
- Its value can later be normalized against the demand values of other Sections to determine
  proportional capacity.
- Unlike `importance`, `demand` describes expected context-space requirement, not semantic value.

---

## Comparison

```text
importance
    → How valuable/important is the information?

demand
    → How much context space does the Section naturally require?
```

`importance` is about **worth**; `demand` is about **space**. A Section can be highly important
yet small (e.g. User Input), and it can be less important yet bulky (e.g. Retrieved Chunks). The
two properties are independent and must be set independently on every Section.

### Example Sections

| Section | `importance` (conceptual) | `demand` (conceptual) |
|---|---|---|
| User Input | very high — the answer depends on it | low — usually a short query |
| Retrieved Chunks | high — the factual basis of the answer | high — many/large items |
| History | medium — context, not the core question | relatively high — can grow |
| System Input | high — governs how the model behaves | low — typically concise instructions |
| Output Format | relatively low — structural, not content | very low — small constant text |

> The values above are **conceptual** reference points. Actual per-Section defaults are defined by
> each concrete `ISection` subclass.