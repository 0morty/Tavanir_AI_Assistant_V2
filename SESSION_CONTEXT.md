# Session Context — Reference-Based Source Enrichment (cont.)

# Session purpose

The new session's purpose is to **implement the ENTIRE `docs/documentation/reference_architecture.md`** —
every component and design rule in it (§1–29). Work through it systematically; the gap list in
§3 below is authoritative for what remains.

Continuation file generated to resume work in a **new session** without losing history.
Read `AGENTS.md` first (it is authoritative). This file records the **Reference Architecture**
build-out, the design decisions that were corrected along the way, and the precise state of the repo.

---

## 1. TL;DR status

- Branch: **`feat/context-builder`** (remote `origin` = `ssh://Administrator@git.jadoosoft.ir:2222/JaddoSoft/Tavanir_AI_Assistant_V2.git`)
- Local is **3 commits ahead** of `origin/feat/context-builder` — **need a push**:
  - `af94ac2 feat(context): add ReferencedCollectionSection`
  - `85ee582 feat(reference): add deterministic ReferenceGenerator fallback`
  - `8e983e5 feat(reference): add TemplateValidator`
- Committed session history:
  - `3b0b826 feat(domain): add Reference entity and ReferenceDetails`
  - `91fc3e9 feat(context): add ReferencedSection base`
  - `07beb28 docs: add reference architecture design document`
  - `af94ac2 feat(context): add ReferencedCollectionSection`
  - `85ee582 feat(reference): add deterministic ReferenceGenerator fallback`
  - `8e983e5 feat(reference): add TemplateValidator`
- Untracked (NOT committed): `SESSION_CONTEXT.md`, `src/application/context/context_builder.py`, `tests/unit/context/test_context_builder.py`.

---

## 2. Files created / modified this session

| File | Purpose |
|---|---|
| `docs/documentation/reference_architecture.md` | Design spec. **Moved & renamed** from `how_referencing_works.md` (was at repo root). User rejected "enrichment" in the name. |
| `src/domain/entities.py` | ADDED (additive only): `Reference` (ABC), `ReferenceDetails` (frozen dataclass), `ReferenceItem` (frozen dataclass). |
| `src/application/context/sections/referenced_section.py` | `ReferencedSection(PromptSection)` — reference-aware section base. |
| `src/application/context/sections/referenced_collection_section.py` | `ReferencedCollectionSection(ReferencedSection)` — collection of reference-bearing items. |
| `src/application/interfaces/i_reference_generator.py` | `IReferenceGenerator` port — `generate(reference) -> str`. |
| `src/application/reference/deterministic_reference_generator.py` | `DeterministicReferenceGenerator` — deterministic (no LLM) generator. |
| `src/application/reference/template_validator.py` | `TemplateValidator`, `TemplateValidationResult`, `extract_placeholders` — template validation (see §3). |
| `src/application/reference/__init__.py` | Exports `DeterministicReferenceGenerator`, `TemplateValidator`, `TemplateValidationResult`, `extract_placeholders`. |
| `src/application/interfaces/__init__.py` | Exports `IReferenceGenerator`. |
| `src/application/context/sections/__init__.py` | Exports `ReferencedSection`, `ReferencedCollectionSection`. |
| `tests/unit/reference/test_template_validator.py` | 8 unit tests (see §6). |

---

## 3. Reference Architecture — implementation progress

Design doc: `docs/documentation/reference_architecture.md` (numbered sections 1–29).

Hierarchy so far:
```
IPromptSection (port / contract only)
   └── PromptSection (skeleton: contract + defaults)
          └── ReferencedSection
                 └── ReferencedCollectionSection
```

Resolution flow (doc §18):
```
Reference.fluent_text()
   ├─ success → return text
   └─ NotImplementedError → ReferenceGenerator.generate(reference)  → concrete text
         (today: DeterministicReferenceGenerator; planned: template from ReferenceCache
          keyed by ReferenceDetails.hash() → substitute_placeholders → deterministic generator)
```

### Build order followed (user said: do one step at a time, "Don't implement future.")
1. `Reference` + `ReferenceDetails` (domain) — done
2. `ReferencedSection` — done
3. `ReferencedCollectionSection` — done
4. Simplified deterministic `ReferenceGenerator` fallback — done
5. `TemplateValidator` (§16) — done
6. LLM-based generator (§14) + `ReferenceCache` (§17) + placeholder substitution (§15) — **NOT done, BLOCKED**

### Doc coverage vs `reference_architecture.md`
- **Implemented:** §1–2 (concepts), §3–4 (section hierarchy), §6–8 (`Reference`, `ReferenceDetails`,
  None/available-property exclusion), §9–10 (canonical + hash), §11–12 (`fluent_text()` optional/
  `NotImplementedError`), §13 (generator, concrete-text contract), §16 (`TemplateValidator`),
  §19–22 (template method, collection behavior, missing references),
  §23–29 (separation, dependency direction, rules).
- **Not yet implemented:** §14 LLM-based `ReferenceGenerator`, §15 placeholder substitution,
  §17 `ReferenceCache`, and the §18 `MISS → LLM` branch — user stated the LLM generator
  needs **ContextBuilder completed first**.
- **`TemplateValidator` behavior (new spec, supersedes the earlier session's plan):**
  extracts `[property_name]` placeholders with a regex, validates **existence only** against
  `ReferenceDetails.properties` (`(name, type)` tuples), and reports unknown properties via
  `TemplateValidationResult(valid, missing)` — it does **not** raise. Repeated valid
  placeholders are not violations; a template without placeholders is valid; a property whose
  value is `None` is valid as long as it exists in `ReferenceDetails`. Deep semantic
  consistency with the `Reference.description` is LLM-judged (not machine-checkable) —
  documented in the validator docstring.
- **Optional / illustrative (NOT required to implement the doc):** concrete subtypes
  `RegulationReference`, `WebReference`, `DocumentReference` (§6/§25 examples). Do not add them
  unless the user asks.

### ContextBuilder (added in the continuation session)
- `src/application/context/context_builder.py` — **`ContextBuilder`** (the Context Manager /
  allocator of `dynamic_section_capacity_allocation.md`). Renders `PromptSection`s, assigns **initial
  capacity by `demand`**, fits over-capacity sections via their **overflow strategy chain**, and
  **redistributes free capacity iteratively by `importance`** (capped at actual need, re-normalized).
  Separator (`\n\n`) token cost is reserved out of the budget; output never exceeds the budget.
  Overflow execution: enum→executor map (`TruncateStrategy` on the injected domain `Tokenizer`,
  `SummarizeStrategy` on an injected `Summarizer`, `IgnoreStrategy`); unavailable strategies are
  skipped; a Section nothing can fit is excluded. Exported from `src/application/context/__init__.py`.
  Tests: `tests/unit/context/test_context_builder.py` (12 passing, manual runner).
- NOTE: two tokenizer abstractions exist — the domain `Tokenizer` (`src/domain/context/tokenizer.py`,
  offset-paired `encode`, used by `TruncateStrategy`) vs `src/application/interfaces/i_tokenizer.py`
  (`ITokenizer`, `tokenize`/`count_tokens`/`decode`). ContextBuilder uses the **domain** one.
- This was built to unblock the LLM-based ReferenceGenerator (§14), which will use it to assemble
  its prompt. Whether the LLM generator should take a `ContextBuilder`-built prompt or a simpler
  string is an open design decision for the next session.

---

## 4. Design decisions corrected during the session — DO NOT REGRESS

These were explicit user corrections. Follow them.

1. **`append_reference()` takes NO `content` parameter.** Content comes from `self.body()`
   (the existing `PromptSection` body method). The user rejected passing content as an argument.

2. **`reference` property belongs ONLY on `ReferencedSection`, NOT on `PromptSection`.**
   `PromptSection` (`src/application/context/sections/prompt_section.py`) was NOT modified and has no reference awareness.

3. **`ReferenceGenerator.generate()` MUST return CONCRETE natural-language text with actual
   values** — never a placeholder template. This is the contract on `IReferenceGenerator`.
   Example (user-supplied):
   - OK:  `در فصل 2 ام و در صفحه 43، نویسنده می گوید:`
   - NOT: `در فصل [chapter] ام و در صفحه [page]، نویسنده می گوید:`
   - Templates (`[page]`, `[title]`, …) and the cache are **internal implementation details** only.

4. **`ReferenceCache` stores TEMPLATES** (with placeholders), keyed by `ReferenceDetails.hash()`
   = property-SHAPE hash (e.g. `page|int,title|str`), at `.cache/references/{hash}.txt`
   (`.cache` is gitignored). A cached template serves ANY instance with the same shape;
   substitution happens per instance inside `generate()`.

   History of the mistake (avoid repeating): we first cached/substituted final text, then
   cached templates but exposed them via the port. Final correct shape = port returns concrete
   text; template cache is internal to the generator.

5. **Missing references are valid.** `reference=None` / empty content → content unchanged.
   `ReferenceDetails` excludes `None` properties → different shapes → different hashes.

6. **Template Method pattern**: `ReferencedSection` owns resolve+compose flow;
   `compose_referenced_content(reference_text, content)` is the overridable hook.
   Collection default loops items independently; custom strategies override `append_references()`.

7. **Doc placement/name**: the design doc is `docs/documentation/reference_architecture.md`
   (snake_case, under `docs/documentation/` with the section docs). Do not move it back.

---

## 5. Reference entity behavior recap

- `Reference(ABC)` — abstract `description`; concrete `details` (auto `ReferenceDetails.from_instance(self)`);
  `fluent_text()` raises `NotImplementedError` by default (signals "use the generator", NOT an error).
- `ReferenceDetails` — frozen dataclass of `(name, type)` property tuples (None excluded);
  `canonical()` sorts `name|type` descriptors; `hash()` = SHA-256 of canonical string.
- `ReferenceItem` — `content: str`, `reference: Reference | None`.

Note: `src/domain/entities.py` is listed in `AGENTS.md` §2.2 as read-only/shared, but new
Reference entities were ADDED there at the user's direction (purely additive, existing code untouched).

---

## 6. Tests & validation

- `tests/unit/reference/test_template_validator.py` — 8 tests: template with only valid properties,
  unknown property, mixed valid+unknown, repeated valid placeholders (not a violation),
  None-valued-but-present property, no placeholders (valid), placeholder dedup/extraction order,
  frozen `TemplateValidationResult` shape.
  (The deterministic generator's tests exist only as a stale `__pycache__` remnant on this branch —
  no `test_deterministic_reference_generator.py` source file is currently present.)
- Existing test dirs are populated: `tests/unit/{context,domain,infrastructure,...}`,
  `tests/unit/context/test_section.py` etc.
- **pytest is NOT installed** in `/usr/bin/python3` (system is externally-managed, no pip; user said
  **"Do not install pytest!"**). Tests were validated with a manual inline runner
  (`python3 -c` temp-dir loop invoking each `test_*` function). If you have access to a venv with
  pytest, use it; otherwise keep the manual runner approach.
- `pytest.ini`: `pythonpath = .`, `testpaths = tests`, `asyncio_mode = strict`.

---

## 7. Environment / rules reminders

- Run commands from repo root; imports are absolute (`from src....`).
- `.env` loads from repo root; local defaults point at TEI localhost:8080 and vLLM localhost:8000.
- `openai` and `dependency-injector` are imported but NOT in `requirements.txt` (pre-existing gotcha).
- Push works; server prints `failed to sync branch to DB` warning after push — ignore, push succeeds.

---

## 8. Next steps

Order matters. The user explicitly stated the LLM-based generator needs **ContextBuilder completed first**.

1. **Push the 3 unpushed commits** (or wait for user request).
2. Implement the ENTIRE reference_architecture.md (the session purpose). Gap state:
   - `TemplateValidator` (§16) — done (new spec; see §3). Generator wiring of the validator
     not yet needed: `DeterministicReferenceGenerator` does not produce templates.
   - **LLM-based `ReferenceGenerator` (§14) + `ReferenceCache` (§17) + placeholder substitution (§15)
     + the §18 MISS→LLM branch — BLOCKED on ContextBuilder completion
     (`src/application/context/context_builder.py` is implemented but untracked).**
   - Concrete `Reference` subtypes (§6/§25) — optional/illustrative, do not add unless asked.
3. Keep the corrected design decisions in §4.

---

## 9. What NOT to do

- Do not re-expose placeholder templates through `IReferenceGenerator.generate()`.
- Do not add `content` params to `append_reference()` or move `reference` onto `PromptSection`.
- Do not reinstall pytest against the system python.
- Do not rename/move `reference_architecture.md`.
- Do not modify out-of-scope code per `AGENTS.md` (retrieval, embeddings, vector DB, frontend, .NET system, …).
- Commit with short Conventional Commit messages; commit only when the user asks.