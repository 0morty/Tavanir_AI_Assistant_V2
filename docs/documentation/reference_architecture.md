# Reference-Based Source Enrichment Architecture

## 1. Purpose

The purpose of this design is to provide a **general, modular, and extensible mechanism** for incorporating source/reference information into the content of Sections.

A `Section` may optionally contain a `Reference` that describes where its content originated, such as:

* page
* article
* chapter
* title
* author
* document
* URL
* date
* or any other domain-specific metadata

The final result should not expose this metadata as a raw key-value structure. Instead, it should be incorporated into the content as **natural human-readable text**.

For example:

### Original Content

```text
Employees must enter the company between 06:30 and 08:00.
```

### Reference

```text
page = 10
article = 12
chapter = "Mandatory Rules"
author = "Hamid Jafari"
```

### Enriched Content

```text
On page 10, in Chapter "Mandatory Rules", Article 12,
written by Hamid Jafari, it is stated:

Employees must enter the company between 06:30 and 08:00.
```

---

# 2. Core Design Principles

The architecture is based on the following principles.

### 2.1 Polymorphism Instead of Central Type Dispatch

The system must not contain a central component such as:

```python
if isinstance(section, ChunkSection):
    ...
elif isinstance(section, HistorySection):
    ...
elif isinstance(section, RegulationSection):
    ...
```

Each Section type should inherit the appropriate behavior from the Section hierarchy and override it only when necessary.

### 2.2 Reference Is a Domain Entity

`Reference` is not merely an interface or DTO.

It is a domain entity that contains:

* its own properties
* semantic description
* structural metadata
* behavior for producing a human-readable representation

Conceptually:

```text
Reference = State + Description + Details + Behavior
```

The `fluent_text()` method is therefore considered a valid behavior of the `Reference` entity.

### 2.3 Separation of Composition and Generation

The Section hierarchy decides **how and where** a Reference is attached to content.

The Reference ecosystem decides **how the Reference itself is represented as human-readable text**.

Therefore:

```text
Section
    → Reference placement/composition

Reference
    → Reference identity and native behavior

ReferenceGenerator
    → External generation when native behavior is unavailable
```

---

# 3. Section Hierarchy

The Section hierarchy is intentionally simple:

```text
Section
   ↓
ReferencedSection
   ↓
ReferencedCollectionSection
```

## 3.1 Section

`Section` remains the general base class.

Sections that do not require references continue to inherit directly from it.

```text
Section
├── NormalSection
├── ...
└── ReferencedSection
```

---

## 3.2 ReferencedSection

`ReferencedSection` is the base class for Sections that can associate a Reference with their content.

Conceptually:

```python
class ReferencedSection(Section):

    reference: Reference

    def append_reference(self, content: str) -> str:
        ...
```

Its responsibilities are:

1. Hold a `Reference`.
2. Resolve the human-readable representation of that Reference.
3. Apply that representation to the Section content.
4. Provide default composition behavior.
5. Allow subclasses to override the composition behavior.

A typical default behavior may be:

```text
Reference Text
+
Content
```

For example:

```text
On page 10, written by Hamid Jafari, it is stated:

Employees must enter the company between 06:30 and 08:00.
```

---

# 4. ReferencedCollectionSection

`ReferencedCollectionSection` extends `ReferencedSection` for Sections whose content is represented as a collection of items.

```text
Section
   ↓
ReferencedSection
   ↓
ReferencedCollectionSection
```

Potential consumers include:

```text
ChunkSection
HistorySection
RegulationSection
...
```

The important property is not the concrete Section type, but the fact that the Section contains multiple independently referenceable items.

Its default behavior can therefore operate over the collection:

```text
for each item:
    resolve item reference
    append reference to item content
```

Conceptually:

```python
class ReferencedCollectionSection(ReferencedSection):

    items: Sequence

    def append_references(self):
        for item in self.items:
            ...
```

A subclass may override this behavior when its domain requires a different composition strategy.

---

# 5. Why the Section Hierarchy Is Important

The inheritance hierarchy eliminates the need for a central dispatcher.

For example, when a new Section is introduced:

```python
class SearchResultSection(ReferencedCollectionSection):
    ...
```

it automatically inherits the default reference behavior.

No change is required in:

* `ContextBuilder`
* `ReferenceGenerator`
* a global resolver
* a registry of Section types

If a custom behavior is required, the Section can override the appropriate method.

This follows the principle:

> Add new behavior through inheritance and overriding, rather than modifying centralized type-dependent logic.

---

# 6. Reference Entity

`Reference` is the primary contract between the Retrieval side and the Generation API.

A producer that sends a reference-bearing object to the Generation API does not need to expose a Retrieval-specific implementation. The Generation API interacts with the source information through the `Reference` abstraction.

Conceptually:

```python
class Reference(ABC):
    ...
```

A concrete Reference may look like:

```python
class RegulationReference(Reference):

    page: int
    article: int
    chapter: str
    author: str
```

Another implementation could be:

```python
class WebReference(Reference):

    title: str
    url: str
    domain: str
```

or:

```python
class DocumentReference(Reference):

    document_title: str
    page: int
    section: str
```

The core system does not need to know the concrete Reference type.

---

# 7. Reference Responsibilities

A Reference exposes three important concepts.

```text
Reference
├── Description
├── ReferenceDetails
└── fluent_text()
```

## 7.1 Description

`Description` explains the purpose and semantics of the Reference.

It should help a developer or an LLM understand what the Reference represents.

For example:

```text
Identifies the location and authorship of a regulation fragment.
```

The Description describes the **meaning of the Reference**, not its final human-readable text.

---

## 7.2 ReferenceDetails

`ReferenceDetails` provides a structural description of the Reference.

It describes the available properties of the Reference rather than the runtime values of those properties.

For example:

```text
| Name    | Type   | Description                    |
|---------|--------|--------------------------------|
| page    | int    | Page containing the content    |
| title   | str    | Title of the source            |
| author  | str    | Author of the source           |
```

The important distinction is:

```text
Reference
    → contains property values

ReferenceDetails
    → describes the properties that are currently available
```

`ReferenceDetails` does not use runtime property values to identify the Reference structure.

---

# 8. ReferenceDetails and Available Properties

A property is considered part of `ReferenceDetails` only when its value is available.

For example:

```python
Reference(
    title="Company Regulations",
    page=10,
    author=None
)
```

produces:

```text
page|int,title|str
```

The `author` property is excluded because its value is `None`.

This behavior is intentional.

It means that different instances of the same Reference class may produce different Reference Details depending on which properties are available.

For example:

### Instance A

```text
title = "Company Regulations"
page = 10
author = None
```

ReferenceDetails:

```text
page|int,title|str
```

### Instance B

```text
title = "Company Regulations"
page = 10
author = "Hamid Jafari"
```

ReferenceDetails:

```text
author|str,page|int,title|str
```

These two References therefore represent different available property sets.

---

# 9. ReferenceDetails Hash

`ReferenceDetails` provides a deterministic hash used for identifying the **shape of the available Reference properties**.

The hash does not represent a specific Reference instance.

It represents the structural combination of its available properties.

## 9.1 Canonical Representation

Property descriptors are normalized into a canonical textual representation:

```text
property_name|property_type
```

Examples:

```text
page|int
title|str
author|str
```

The entries are sorted alphabetically by property name.

For example:

```text
title|str
page|int
author|str
```

becomes:

```text
author|str,page|int,title|str
```

This canonical string is then hashed.

Conceptually:

```python
properties = sorted(properties)
canonical = ",".join(properties)
hash = hash_function(canonical)
```

The exact hash algorithm may be defined by the implementation, but the canonicalization process must be deterministic.

---

# 10. Meaning of the ReferenceDetails Hash

The hash identifies a **Reference Property Shape**.

Therefore:

```text
page|int,title|str
```

always produces the same hash, regardless of the actual values:

```text
page = 10
title = "Regulations"
```

or:

```text
page = 75
title = "Employee Rules"
```

Both instances have the same structural shape:

```text
page|int,title|str
```

and therefore the same ReferenceDetails hash.

Conversely:

```text
page|int,title|str
```

and:

```text
author|str,page|int,title|str
```

must produce different hashes.

---

# 11. Native Fluent Text

A Reference may implement:

```python
def fluent_text(self) -> str:
    ...
```

This is an optional native rendering behavior.

For example:

```python
class SimpleReference(Reference):

    page: int

    def fluent_text(self) -> str:
        return f"On page {self.page}, it is stated:"
```

The advantage is that simple or highly specialized References can provide their own deterministic representation without involving an LLM.

---

# 12. `fluent_text()` Is Optional

Not every Reference needs to implement `fluent_text()`.

A Reference may intentionally rely on the external generation mechanism.

Therefore, the base implementation can signal that native rendering is unavailable:

```python
raise NotImplementedError
```

This does not mean the Reference is invalid.

It means:

> This Reference does not provide its own native fluent-text implementation.

The caller must then use the fallback generation mechanism.

A dedicated domain-specific exception may later be introduced if a more precise semantic distinction is required.

---

# 13. ReferenceGenerator

`ReferencedSection` should not be responsible for generating fluent human language itself.

That responsibility belongs to a dedicated engine:

```text
ReferenceGenerator
```

Its purpose is to convert the structural information of a Reference into a human-readable representation when the Reference does not provide one natively.

Conceptually:

```text
Reference
    ↓
ReferenceDetails
    ↓
ReferenceGenerator
    ↓
Human-readable Reference Text
```

The Generator should not know or care whether the Reference belongs to:

* a Chunk
* History
* Regulation
* Web content
* any other Section

It operates exclusively on the Reference abstraction.

---

# 14. LLM-Based Reference Generation

The `ReferenceGenerator` may use an LLM to convert the Reference structure into a natural-language template.

For example:

### Input

```text
Description:
Identifies the location and authorship of a regulation fragment.

Properties:

page | int | Page containing the content
title | str | Title of the source
author | str | Author of the source
```

### Generated Template

```text
On page [page], from "[title]", written by [author], it is stated:
```

The LLM generates the language structure, while the application remains responsible for inserting the actual property values.

---

# 15. Placeholder-Based Rendering

The generated text should use explicit property placeholders.

For example:

```text
On page [page], written by [author], it is stated:
```

The LLM must not substitute actual values into the generated template.

Actual values are inserted afterward by deterministic application logic:

```text
Template
    ↓
Placeholder Substitution
    ↓
Final Reference Text
```

For example:

```text
On page [page], written by [author], it is stated:
```

becomes:

```text
On page 10, written by Hamid Jafari, it is stated:
```

This separation provides an important safety property:

> The LLM determines language structure, while the application determines factual property values.

---

# 16. Template Validation

Because the Reference Generator may rely on an LLM, its output must not be treated as automatically valid.

The generated template should be validated before it is used.

Validation should ensure that:

* every placeholder refers to an available property
* no unknown placeholder is introduced
* placeholder syntax is valid
* the generated output does not introduce unsupported properties
* the generated representation remains semantically consistent with the Reference Description and Details

Example:

```text
Available properties:
page
title
author
```

Generated:

```text
On page [page], written by [writer], it is stated:
```

Result:

```text
INVALID
```

because `[writer]` is not an available property.

---

# 17. Reference Cache

Generated Reference text should be cached to avoid repeatedly invoking the LLM for the same Reference Property Shape.

Cache location:

```text
.cache/references/
```

The `ReferenceDetails` hash can be used as the cache key.

Conceptually:

```text
ReferenceDetails
       ↓
      hash
       ↓
.cache/references/{hash}
```

---

# 18. Cache Resolution Flow

The complete resolution process is:

```text
Reference
    ↓
Try reference.fluent_text()
    │
    ├── Success
    │      ↓
    │   Return text
    │
    └── NotImplemented
            ↓
       ReferenceDetails
            ↓
            Hash
            ↓
        Cache Lookup
          │       │
        HIT      MISS
          │       │
          │       ▼
          │  ReferenceGenerator
          │       ↓
          │      LLM
          │       ↓
          │    Template
          │       ↓
          │   Validation
          │       ↓
          │     Cache
          │
          └───────┴──────► Placeholder Substitution
                                  ↓
                            Final Reference Text
```

The cache therefore stores the generated representation associated with a particular Reference Property Shape.

---

# 19. Responsibility of ReferencedSection

`ReferencedSection` coordinates the resolution process but does not implement the generation logic itself.

Conceptually:

```python
class ReferencedSection(Section):

    reference: Reference

    def append_reference(self, content: str) -> str:
        reference_text = self.resolve_reference_text()
        return self.compose_referenced_content(
            reference_text,
            content,
        )
```

The actual resolution may internally follow:

```text
Reference.fluent_text()
        ↓
fallback to ReferenceGenerator
        ↓
cache / generation
```

The important point is that the Section does not understand the internal mechanics of the Reference Generator.

---

# 20. Template Method for Section Composition

The default Reference application behavior should be implemented in `ReferencedSection`, while the actual composition should be overridable.

For example:

```python
class ReferencedSection(Section):

    def append_reference(self, content: str) -> str:
        reference_text = self.resolve_reference_text()

        return self.compose_referenced_content(
            reference_text,
            content,
        )

    def compose_referenced_content(
        self,
        reference_text: str,
        content: str,
    ) -> str:
        return f"{reference_text}\n{content}"
```

A specialized Section can then override only:

```python
compose_referenced_content()
```

instead of reimplementing the entire reference-resolution flow.

This follows the **Template Method Pattern** and prevents subclasses from accidentally bypassing important parts of the process.

---

# 21. Collection Behavior

`ReferencedCollectionSection` provides default behavior for multiple reference-bearing items.

Conceptually:

```text
ReferencedCollectionSection
        │
        └── items
             ├── Item + Reference
             ├── Item + Reference
             └── Item + Reference
```

The default behavior applies Reference handling to each item independently.

A subclass can override the behavior when the collection requires a different strategy.

For example:

```text
Default:
Reference → Item Content
Reference → Item Content
Reference → Item Content

Custom:
Reference 1
Reference 2
Reference 3
    ↓
Combined Content
```

The core system remains unchanged.

---

# 22. Handling Missing References

A Section may have no Reference.

This should be a valid state.

For example:

```text
reference = None
```

The expected behavior is:

```text
No Reference
    ↓
Content remains unchanged
```

For collections, individual items may also have different states:

```text
Item 1 → Reference available
Item 2 → Reference unavailable
Item 3 → Reference available
```

The default collection behavior should process each item independently.

---

# 23. Separation of Concerns

The final architecture should maintain the following responsibility boundaries:

| Component                     | Responsibility                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------- |
| `Section`                     | General Section behavior                                                              |
| `ReferencedSection`           | Reference-aware content composition                                                   |
| `ReferencedCollectionSection` | Default composition for collections of reference-bearing items                        |
| `Reference`                   | Reference entity, its state, description, details, and optional native behavior       |
| `ReferenceDetails`            | Structural description of available Reference properties and deterministic hashing    |
| `ReferenceGenerator`          | Generate human-readable Reference representation when native rendering is unavailable |
| `ReferenceCache`              | Store and retrieve generated Reference representations                                |
| `TemplateValidator`           | Validate generated templates before use                                               |
| Placeholder substitution      | Deterministically insert actual Reference values into the generated template          |

---

# 24. Dependency Direction

The dependency direction should remain one-way.

```text
Section
   ↓
ReferencedSection
   ↓
Reference
```

The Reference subsystem itself:

```text
Reference
   ↓
ReferenceDetails
   ↓
ReferenceGenerator
   ↓
LLM
```

`ReferenceGenerator` must not depend on concrete Section types.

Likewise, `Reference` must not depend on:

* ChunkSection
* HistorySection
* RegulationSection
* ContextBuilder
* PromptBuilder
* Retrieval implementations

This keeps the Reference abstraction reusable across the entire Generation API.

---

# 25. Generality

The architecture is intentionally independent of a specific domain.

The same mechanism can support:

```text
RegulationReference
DocumentReference
WebReference
DatabaseReference
ConversationReference
SearchResultReference
...
```

Likewise, the same Section hierarchy can support:

```text
ChunkSection
HistorySection
RegulationSection
SearchResultSection
...
```

without changing the central Reference-generation mechanism.

---

# 26. Extensibility

To add a new Reference type:

```python
class NewReference(Reference):
    ...
```

No modification to `ReferencedSection` is required.

To add a new Section with reference support:

```python
class NewSection(ReferencedSection):
    ...
```

No modification to a central resolver is required.

To add a new reference-aware collection:

```python
class NewCollectionSection(ReferencedCollectionSection):
    ...
```

The default collection behavior is inherited automatically.

Custom behavior is introduced by overriding the appropriate method.

---

# 27. Complete Architecture

The resulting architecture is:

```text
                         ┌──────────────────┐
                         │     Section      │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ ReferencedSection│
                         │                  │
                         │ reference        │
                         │ append_reference │
                         │ composition hook │
                         └────────┬─────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │ ReferencedCollectionSection│
                    │                           │
                    │ items                     │
                    │ collection reference flow │
                    └───────────────────────────┘


                         ┌─────────────────┐
                         │    Reference    │
                         ├─────────────────┤
                         │ Domain State    │
                         │ Description     │
                         │ ReferenceDetails│
                         │ fluent_text()   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ReferenceDetails
                                  │
                       Available Properties
                                  │
                         Canonicalization
                                  │
                                  ▼
                               Hash
                                  │
                                  ▼
                         Reference Cache
                                  │
                   ┌──────────────┴──────────────┐
                   │                             │
                  HIT                           MISS
                   │                             │
                   │                    ReferenceGenerator
                   │                             │
                   │                             ▼
                   │                            LLM
                   │                             │
                   │                             ▼
                   │                         Template
                   │                             │
                   │                       Validation
                   │                             │
                   └─────────────────────────────┘
                                  │
                                  ▼
                       Placeholder Substitution
                                  │
                                  ▼
                        Final Reference Text
                                  │
                                  ▼
                         ReferencedSection
                                  │
                                  ▼
                         Enriched Content
```

---

# 28. Final Design Rules

The following rules define the intended architecture:

1. `Reference` is a domain entity, not merely a passive DTO.
2. `Reference.fluent_text()` is an optional native behavior of the Reference entity.
3. `ReferenceDetails` describes the currently available property structure of a Reference instance.
4. `ReferenceDetails` does not contain runtime property values.
5. `None` properties are excluded from `ReferenceDetails`.
6. The ReferenceDetails hash identifies the available property shape, not the instance values.
7. Property descriptors are sorted deterministically before hashing.
8. `ReferencedSection` owns the default mechanism for applying Reference text to content.
9. `ReferencedCollectionSection` provides the default behavior for collections.
10. Section-specific behavior is implemented through inheritance and overriding, not centralized type checks.
11. `ReferenceGenerator` is responsible for generating human-readable representations when native rendering is unavailable.
12. LLM-generated templates use explicit property placeholders.
13. Actual Reference values are inserted deterministically by application code.
14. Generated templates are validated before being cached or used.
15. Reference generation must remain independent of concrete Section types.
16. Missing References are valid and must not alter the original content.
17. The core architecture must not depend on a specific LLM provider or retrieval implementation.

---

# 29. Architectural Goal

The ultimate goal is to make Reference enrichment a reusable capability of the Generation API rather than a feature implemented separately for each type of retrieved object.

The desired abstraction is:

```text
Any Reference-aware object
        ↓
ReferencedSection hierarchy
        ↓
Reference
        ↓
Native rendering OR generated rendering
        ↓
Human-readable Reference Text
        ↓
Original Content
        ↓
Enriched Content
```

This provides a system in which new Sections, new Reference types, and new rendering mechanisms can be introduced independently while preserving the existing architecture.
