"""Offline controls for mandatory variant coverage, independent of the builder.

These controls check the actual request parameters as well as stable identities;
an accidental change in the scenario generator cannot shrink the required sets.
They run without E2E opt-in, service startup, or database access.
"""

from __future__ import annotations

from collections import Counter

import pytest

from .scenarios import NORMAL_SCENARIOS


_EDIT_METHODS = ("ingest", "put", "patch")
_STATUS_TABLE = (
    (1, "NOT_ACCEPTED", "عدم پذیرش"),
    (2, "REJECTED", "رد"),
    (3, "APPROVED", "مصوب"),
    (4, "PENDING", "در حال اجرا"),
    (5, "EXECUTED", "اجرا شده"),
)
_NOISE_VALUES = ("-", "--", "---", ".", "..", "...", "ندارد", "بدون شرح", "هیچ", "ثبت نشده", "موردی ندارد", "عدم وجود")
_REQUIRED_SCRUTINY_REPRESENTATIONS = ("integer", "ascii", "persian-digits", "arabic-digits", "enum", "title", "arabic-letters", "half-spaces")


def validate_required_normal_variants(scenarios) -> tuple[str, ...]:
    """Return every absent or malformed required combination, never counts alone."""
    scenarios = tuple(scenarios)
    by_key = {(s.case_id, s.variant_id): s for s in scenarios}
    problems = []
    counts = Counter((s.case_id, s.variant_id) for s in scenarios)
    problems.extend(f"duplicate:{case}/{variant}" for (case, variant), count in counts.items() if count != 1)

    def require(case, variant, *, endpoint=None, field=None, value_marker=False, value=None, expected_id=None, sql_id=None, parameters=None):
        scenario = by_key.get((case, variant))
        description = f"{case}/{variant}"
        if scenario is None:
            problems.append(description)
            return
        params = scenario.parameters
        if endpoint is not None and params.get("endpoint") != endpoint:
            problems.append(description + ":wrong-endpoint")
        if field is not None and params.get("field") != field:
            problems.append(description + ":wrong-field")
        if value_marker and (type(params.get("value")) is not type(value) or params.get("value") != value):
            problems.append(description + ":wrong-value")
        if expected_id is not None and params.get("expected", {}).get(sql_id) != expected_id:
            problems.append(description + ":wrong-stored-code")
        for name, required_value in (parameters or {}).items():
            actual_value = params.get(name)
            if type(actual_value) is not type(required_value) or actual_value != required_value:
                problems.append(description + f":wrong-{name}")

    for endpoint in _EDIT_METHODS:
        for code, enum_name, title in _STATUS_TABLE:
            forms = {
                "integer": code, "ascii": str(code),
                "persian-digits": str(code).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
                "arabic-digits": str(code).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")),
                "enum": enum_name, "title": title,
            }
            for form, value in forms.items():
                require("VAL-10", f"{endpoint}-{code}-{form}", endpoint=endpoint, field="status", value_marker=True, value=value, expected_id=code, sql_id="status_id")
                if isinstance(value, str):
                    require("VAL-10", f"{endpoint}-{code}-{form}-padded", endpoint=endpoint, field="status", value_marker=True, value=f" {value} ", expected_id=code, sql_id="status_id")

        for field, codes, sql_id in (("committeeScrutiny", range(-10, 22), "committee_scrutiny_id"), ("secretariatScrutiny", (*range(-2, 10), 15, 16, 17), "secretariat_scrutiny_id")):
            for code in codes:
                for form in _REQUIRED_SCRUTINY_REPRESENTATIONS:
                    expected = 0 if field == "committeeScrutiny" and code == -3 and form in ("title", "arabic-letters", "half-spaces") else code
                    numeric_value = code if form == "integer" else str(code) if form == "ascii" else str(code).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) if form == "persian-digits" else str(code).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")) if form == "arabic-digits" else None
                    require("VAL-13", f"{endpoint}-{field}-{code}-{form}", endpoint=endpoint, field=field, value_marker=form in ("integer", "ascii", "persian-digits", "arabic-digits"), value=numeric_value, expected_id=expected, sql_id=sql_id)

        for field in ("title", "problem", "solution"):
            shapes = [("number", 11), ("boolean", True), ("array", []), ("object", {})]
            if endpoint != "patch":
                shapes.append(("null", None))
            for shape, value in shapes:
                require("VAL-06", f"{endpoint}-{field}-{shape}", endpoint=endpoint, field=field, value_marker=True, value=value)
            for length in (1, 4, 5):
                require("VAL-08", f"{endpoint}-{field}-length-{length}", endpoint=endpoint, field=field, value_marker=True, value="abcde"[:length])
            for index, value in enumerate(_NOISE_VALUES):
                require("VAL-09", f"{endpoint}-{field}-noise-{index}", endpoint=endpoint, field=field, value_marker=True, value=value)
        for field in ("description", "contextTitle", "secretariatComment"):
            for shape, value in (("number", 7), ("boolean", True), ("array", []), ("object", {})):
                require("VAL-24", f"{endpoint}-{field}-{shape}", endpoint=endpoint, field=field, value_marker=True, value=value)
        for field in ("committeeScrutiny", "description", "shamsiDate", "contextTitle", "secretariatScrutiny", "secretariatComment"):
            for form, value in (("omitted", "__omit__"), ("null", None), ("empty", ""), ("whitespace", "   ")):
                require("VAL-16", f"{endpoint}-{field}-{form}", endpoint=endpoint, field=field, value_marker=True, value=value)

    for endpoint in ("ingest", "put", "patch", "delete", "bulk"):
        require("API-01", f"{endpoint}-missing", endpoint=endpoint)
        require("API-02", f"{endpoint}-wrong", endpoint=endpoint)
        require("API-03", f"{endpoint}-padded-valid", endpoint=endpoint, parameters={"key": "pad-key"})
        require("API-04", f"{endpoint}-capitalized", endpoint=endpoint)
        require("HOST-10", endpoint, endpoint=endpoint)
    # Required categories are stated independently of _variants(). DELETE has
    # no body validation; its missing lookup is the applicable HTTP error case.
    required_correlation_categories = {
        "ingest": ("success", "auth", "validation"),
        "put": ("success", "auth", "validation"),
        "patch": ("success", "auth", "validation"),
        "delete": ("success", "auth", "lookup"),
        "bulk": ("success", "auth", "validation", "bulk-partial"),
    }
    actual_correlation = {
        (s.case_id, s.parameters.get("endpoint"), s.parameters.get("kind"), type(s.parameters.get("supplied")), s.parameters.get("supplied"))
        for s in scenarios if s.operation == "request_id"
    }
    for endpoint, categories in required_correlation_categories.items():
        for category in categories:
            for case, supplied in (("API-11", False), ("API-11", True), ("API-12", ""), ("API-12", "not-a-uuid")):
                if (case, endpoint, category, type(supplied), supplied) not in actual_correlation:
                    form = "generated" if supplied is False else "supplied" if supplied is True else "empty" if supplied == "" else "malformed"
                    problems.append(f"{case}:required-correlation:{endpoint}:{category}:{form}")
    for endpoint in ("put", "patch", "delete"):
        for side in ("leading", "trailing", "surrounding"):
            require("VAL-26", f"{endpoint}-{side}-path-space", endpoint=endpoint, parameters={"side": side})
    for case in ("ING-04", "PAT-11"):
        for field in ("description", "secretariatComment"):
            for normalization in ("diacritic", "emoji"):
                require(case, f"{field}-raw15-normalized14-{normalization}", field=field, parameters={"variant": "normalized-comment-threshold", "normalization": normalization})
    for separator in ("paragraph", "newline", "persian-punctuation", "word-boundaries"):
        require("ING-06", separator, parameters={"separator": separator, "variant": "long"})
    for normalization in ("zwnj", "whitespace"):
        require("ING-08", normalization, parameters={"unicode_variant": normalization, "variant": "unicode"})
    require("PUT-09", "grow", parameters={"variant": "grow"})
    for position in (0, 1, 2):
        require("BULK-13", f"trimmed-missing-index-{position}", parameters={"variant": "trimmed-partial", "position": position})
    for case, variant in (("FLOW-01", "full-lifecycle"), ("BULK-02", "hundred"), ("BULK-10", "hundred-one"), ("DEL-05", "deleted-orphans"), ("BULK-16", "deleted-orphans"), ("ING-17", "literal-placeholder-and-protected-code")):
        require(case, variant)
    return tuple(sorted(problems))


def test_required_normal_variant_matrix_is_complete():
    assert validate_required_normal_variants(NORMAL_SCENARIOS) == ()


@pytest.mark.parametrize("case,variant", [
    ("VAL-10", "patch-5-arabic-digits-padded"),
    ("VAL-13", "put-committeeScrutiny--10-integer"),
    ("VAL-13", "ingest-secretariatScrutiny-17-title"),
    ("VAL-06", "ingest-title-object"),
    ("VAL-09", "put-solution-noise-11"),
    ("BULK-02", "hundred"),
    ("ING-06", "word-boundaries"),
    ("ING-04", "description-raw15-normalized14-diacritic"),
    ("PAT-11", "secretariatComment-raw15-normalized14-emoji"),
    ("VAL-26", "delete-leading-path-space"),
    ("BULK-13", "trimmed-missing-index-2"),
])
def test_completeness_control_detects_a_removed_mandatory_variant(case, variant):
    reduced = tuple(s for s in NORMAL_SCENARIOS if (s.case_id, s.variant_id) != (case, variant))
    assert f"{case}/{variant}" in validate_required_normal_variants(reduced)


def test_completeness_control_rejects_correct_identity_with_wrong_request_parameters():
    from dataclasses import replace

    original = next(s for s in NORMAL_SCENARIOS if s.case_id == "VAL-10" and s.variant_id == "put-3-integer")
    corrupted = replace(original, parameters={**original.parameters, "value": 4})
    altered = tuple(corrupted if s is original else s for s in NORMAL_SCENARIOS)
    assert "VAL-10/put-3-integer:wrong-value" in validate_required_normal_variants(altered)


def test_completeness_control_detects_missing_endpoint_category_even_when_total_is_preserved():
    from dataclasses import replace

    original = next(s for s in NORMAL_SCENARIOS if s.case_id == "API-11" and s.parameters.get("endpoint") == "bulk" and s.parameters.get("kind") == "validation" and s.parameters.get("supplied") is False)
    replacement = replace(original, parameters={**original.parameters, "endpoint": "patch"})
    altered = tuple(replacement if s is original else s for s in NORMAL_SCENARIOS)
    assert len(altered) == len(NORMAL_SCENARIOS)
    assert "API-11:required-correlation:bulk:validation:generated" in validate_required_normal_variants(altered)


@pytest.mark.parametrize("normalization", ("diacritic", "emoji"))
def test_reviewed_threshold_fixture_crosses_raw_normalized_boundary(normalization):
    from .scenarios import _normalized_threshold_fixture

    raw, golden = _normalized_threshold_fixture(normalization)
    assert len(raw) == 15
    assert golden == "abcdefghijklmn" and len(golden) == 14


@pytest.mark.parametrize("explicit_pointer", (None, "/data/contextTitle"))
def test_generic_server_error_does_not_invent_a_field_pointer_but_retains_explicit_requirements(explicit_pointer):
    import json
    from types import SimpleNamespace

    from .scenarios import _run_validation

    body = {"errors": [{"status": 500, "code": "INTERNAL_ERROR"}]}

    class OfflineHarness:
        def __init__(self):
            self.requests = []
            self.snapshots = []

        def new_id(self, label):
            return "e2e-offline-server-error"

        def snapshot(self, parent_id):
            self.snapshots.append(parent_id)
            return {"sql": None, "points": []}

        def request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            return SimpleNamespace(status_code=500, text=json.dumps(body), json=lambda: body)

    harness = OfflineHarness()
    if explicit_pointer is None:
        _run_validation(harness, "ingest", field="contextTitle", value="x" * 256, status=500, code="INTERNAL_ERROR")
        assert harness.snapshots == ["e2e-offline-server-error"] * 2
    else:
        with pytest.raises(AssertionError):
            _run_validation(harness, "ingest", field="contextTitle", value="x" * 256, status=500, code="INTERNAL_ERROR", pointer=explicit_pointer)
    assert len(harness.requests) == 1
    method, path, kwargs = harness.requests[0]
    assert method == "POST" and path == "/api/v1/suggestions/ingest"
    assert kwargs["json"]["contextTitle"] == "x" * 256


@pytest.mark.parametrize("status,corrupt_store,valid", [
    (201, False, True),
    (201, True, False),
    (422, False, True),
    (422, True, False),
    (500, False, False),
])
def test_headerless_json_characterization_requires_consistent_success_or_write_free_validation(status, corrupt_store, valid):
    import copy
    import json
    import uuid
    from types import SimpleNamespace

    from .scenarios import BASE_GOLDEN, _run_media

    parent = "e2e-offline-media"
    row = {
        "id": parent, **BASE_GOLDEN, "status_id": 3, "version": 1,
        "is_deleted": False, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "context_title": None, "shamsi_date": None, "committee_scrutiny": None,
        "committee_scrutiny_id": None, "secretariat_scrutiny": None,
        "secretariat_scrutiny_id": None, "description": None, "secretariat_comment": None,
    }
    points = []
    for field in ("title", "problem", "solution"):
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{parent}/{field}"))
        points.append({"id": chunk_id, "payload": {
            "parent_id": "incorrect-parent" if status == 201 and corrupt_store else parent,
            "chunk_id": chunk_id, "chunk_type": field, "sub_index": 0,
            "chunk_status": "active", "status": "مصوب", "content": row[field], "version": row["version"],
        }, "vector": {"dense": [0.1, 0.2], "sparse": {"indices": [], "values": []}}})
    persisted = {"sql": row, "points": points}
    response_body = {"status": 201, "data": {"suggestionId": parent, "status": "CREATED", "chunksCount": 3}} if status == 201 else {"errors": [{"status": status, "code": "VALIDATION_ERROR" if status == 422 else "INTERNAL_ERROR"}]}

    class OfflineHarness:
        config = SimpleNamespace(dense_name="dense", sparse_name="sparse", dense_dimension=2, max_chunk_chars=1500)

        def __init__(self):
            self.reads = 0
            self.requests = []

        def new_id(self, label):
            return parent

        def snapshot(self, parent_id):
            assert parent_id == parent
            self.reads += 1
            if self.reads == 1 or status == 422 and not corrupt_store:
                return {"sql": None, "points": []}
            return copy.deepcopy(persisted)

        def request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            return SimpleNamespace(status_code=status, text=json.dumps(response_body), json=lambda: response_body)

    harness = OfflineHarness()
    if valid:
        _run_media(harness, "ingest", media=None, accepted=True)
        assert harness.reads == 2
    else:
        with pytest.raises(AssertionError):
            _run_media(harness, "ingest", media=None, accepted=True)
    assert harness.requests[0][2]["headers"] == {}
    assert json.loads(harness.requests[0][2]["content"])["suggestionId"] == parent


def test_authentication_oracle_rejects_acceptance_of_a_transmitted_padded_valid_key():
    import json
    from types import SimpleNamespace

    from .scenarios import _run_authentication

    parent = "e2e-offline-padded-key"
    body = {"status": 201, "data": {"suggestionId": parent, "status": "CREATED", "chunksCount": 3}}

    class OfflineHarness:
        config = SimpleNamespace(api_header="X-Api-Key", api_key="offline-review-key")

        def __init__(self):
            self.requests = []
            self.reads = 0

        def new_id(self, label):
            return parent

        def snapshot(self, parent_id):
            self.reads += 1
            return {"sql": None, "points": []}

        def request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            return SimpleNamespace(status_code=201, text=json.dumps(body), json=lambda: body)

    harness = OfflineHarness()
    with pytest.raises(AssertionError, match="HTTP 201, expected 401"):
        _run_authentication(harness, "ingest", key="pad-key")
    assert harness.reads == 1, "an accepted padded credential entered a success/store oracle"
    kwargs = harness.requests[0][2]
    assert kwargs["headers"] == {"X-Api-Key": " offline-review-key "}
    assert kwargs["raw_headers"] is True and kwargs["auth"] is False


__all__ = ["validate_required_normal_variants"]
