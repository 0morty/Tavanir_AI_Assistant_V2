"""Pure controls for representative historical sampling; no service or DB use."""

from __future__ import annotations

import copy
import hashlib
import random

import pytest

from .sample import select_representative_sample


def _record(status, parent_id, *, description=None, secretariat=None, context=None, date=None, problem="energy equipment", chunks=3):
    return {"sql": {
        "id": parent_id, "status_id": status, "title": "energy title", "problem": problem,
        "solution": "energy solution", "description": description, "secretariat_comment": secretariat,
        "context_title": context, "shamsi_date": date, "version": 7,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
    }, "points": [{"id": f"{parent_id}-point-{index}", "payload": {"parent_id": parent_id},
                   "vector": {"dense": [0.1, 0.2], "sparse": {"indices": [index], "values": [0.5]}}} for index in range(chunks)]}


def test_default_sample_balances_all_five_statuses_and_hashes_break_equal_variation_ties():
    records = [_record(status, f"status-{status}-{index:03d}") for status in range(1, 6) for index in range(30)]
    sample = select_representative_sample(records)
    assert sample["selected"] == 100 and sample["shortage"] == 0
    assert sample["status_counts_selected"] == {status: 20 for status in range(1, 6)}
    for status in range(1, 6):
        actual = [record["sql"]["id"] for record in sample["records"] if record["sql"]["status_id"] == status]
        required = sorted((record["sql"]["id"] for record in records if record["sql"]["status_id"] == status), key=lambda value: hashlib.sha256(value.encode()).hexdigest())[:20]
        assert actual == required


def test_short_status_quota_is_filled_fairly_from_remaining_qualified_records():
    records = [_record(status, f"status-{status}-{index:03d}") for status in range(1, 6) for index in range(2 if status == 1 else 35)]
    sample = select_representative_sample(records)
    assert sample["selected"] == 100 and sample["shortage"] == 0
    assert sample["status_counts_selected"][1] == 2 and sample["status_shortages"][1] == 18
    assert all(24 <= sample["status_counts_selected"][status] <= 25 for status in range(2, 6))
    assert sample["unavailable_statuses"] == []


def test_underpopulated_source_reports_shortage_and_absent_categories_without_fabricating_records():
    records = [_record(3, f"only-approved-{index}") for index in range(19)]
    sample = select_representative_sample(records)
    assert sample["selected"] == 19 and sample["shortage"] == 81
    assert sample["unavailable_statuses"] == [1, 2, 4, 5]
    assert sample["unavailable_categories"]["context"] == ["present"]
    assert sample["unavailable_categories"]["date"] == ["present"]
    assert "zwnj" in sample["unavailable_categories"]["unicode"]
    assert {record["sql"]["id"] for record in sample["records"]} == {record["sql"]["id"] for record in records}


def test_diversity_is_prioritized_over_duplicate_shapes_within_one_status():
    diverse = [
        _record(3, "none"), _record(3, "short", description="abcd"),
        _record(3, "committee", description="a substantive committee comment", context="grid-west", date="1401/01/02", problem="بهینه‌سازی", chunks=4),
        _record(3, "secretariat-۳", secretariat="a substantive secretariat comment", context="grid-east", date="1402/02/03", chunks=5),
        _record(3, "both", description="a substantive committee comment", secretariat="a substantive secretariat comment", context="grid-east", date="1403/03/04", problem="e\u0301😀", chunks=6),
    ]
    records = diverse + [_record(3, f"duplicate-{index}") for index in range(20)]
    sample = select_representative_sample(records, sample_size=5)
    assert sample["selected_categories"]["commentary"] == ["both", "committee_only", "none", "secretariat_only", "short"]
    assert sample["selected_categories"]["context"] == ["absent", "present"]
    assert sample["selected_categories"]["date"] == ["absent", "present"]
    assert sample["selected_categories"]["chunk_count"] == ["five_or_more", "four", "up_to_three"]
    assert {"zwnj", "persian_digits", "combining_marks", "supplementary_codepoints"} <= set(sample["selected_categories"]["unicode"])


def test_available_but_omitted_categories_are_distinguished_from_unavailable_source_categories():
    sample = select_representative_sample([_record(3, "plain"), _record(3, "rich", description="a substantive committee comment", context="grid", date="1403/01/02", chunks=4)], sample_size=1)
    assert "none" in sample["available_not_selected_categories"]["commentary"]
    assert "none" not in sample["unavailable_categories"]["commentary"]
    assert "both" in sample["unavailable_categories"]["commentary"]


def test_selection_is_invariant_to_capture_and_point_order_and_does_not_mutate_snapshots():
    records = [_record(status, f"s{status}-{index}", context=f"context-{index % 3}", date=f"1403/01/{index + 1:02d}", chunks=3 + index % 5) for status in range(1, 6) for index in range(25)]
    baseline = copy.deepcopy(records)
    expected = select_representative_sample(records, sample_size=30)
    reordered = copy.deepcopy(records)
    random.Random(19).shuffle(reordered)
    # Point order is preserved in each capture, but cannot alter selection IDs.
    for record in reordered:
        record["points"].reverse()
    actual = select_representative_sample(reordered, sample_size=30)
    assert [record["sql"]["id"] for record in actual["records"]] == [record["sql"]["id"] for record in expected["records"]]
    assert {key: value for key, value in actual.items() if key != "records"} == {key: value for key, value in expected.items() if key != "records"}
    assert records == baseline
    expected["records"][0]["points"][0]["vector"]["dense"][0] = 999
    assert records == baseline, "returned mutable export aliases the raw capture"


@pytest.mark.parametrize("sample_size", (0, -1, True, "100"))
def test_invalid_sample_size_is_rejected(sample_size):
    with pytest.raises(ValueError, match="positive integer"):
        select_representative_sample([], sample_size=sample_size)


def test_empty_qualified_source_reports_all_unavailable_statuses_and_categories():
    sample = select_representative_sample([])
    assert sample["records"] == [] and sample["shortage"] == 100
    assert sample["unavailable_statuses"] == [1, 2, 3, 4, 5]
    assert all(not values for values in sample["available_categories"].values())


def test_duplicate_ids_are_rejected_instead_of_duplicating_one_historical_suggestion():
    with pytest.raises(ValueError, match="duplicate qualified SQL ID"):
        select_representative_sample([_record(1, "same"), _record(2, "same")])
