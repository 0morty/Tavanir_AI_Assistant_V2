"""Deterministic diversity selection from already-qualified raw test snapshots.

Qualification, aliases, drift checks, credentials, and storage remain the
caller's responsibility. This module reads no service and imports no production
code. Selected records are exact deep copies of the supplied captures.
"""

from __future__ import annotations

import copy
import hashlib
import unicodedata
from collections.abc import Iterable
from typing import Any


_STATUSES = (1, 2, 3, 4, 5)
_CATEGORY_UNIVERSE = {
    "commentary": ("none", "short", "committee_only", "secretariat_only", "both"),
    "context": ("absent", "present"),
    "date": ("absent", "present"),
    "unicode": ("ascii_only", "non_ascii", "zwnj", "persian_digits", "arabic_indic_digits", "combining_marks", "supplementary_codepoints"),
    "chunk_count": ("up_to_three", "four", "five_or_more"),
}


def _variation(snapshot: dict[str, Any]) -> tuple[dict[str, frozenset[str]], dict[str, set[str]]]:
    row = snapshot["sql"]
    description = (row.get("description") or "").strip()
    secretariat = (row.get("secretariat_comment") or "").strip()
    committee_substantive, secretariat_substantive = len(description) >= 15, len(secretariat) >= 15
    commentary = "both" if committee_substantive and secretariat_substantive else "committee_only" if committee_substantive else "secretariat_only" if secretariat_substantive else "short" if description or secretariat else "none"
    context, date = (row.get("context_title") or "").strip(), (row.get("shamsi_date") or "").strip()
    text = "\n".join(row.get(name) or "" for name in ("id", "title", "problem", "solution", "description", "secretariat_comment", "context_title", "shamsi_date"))
    unicode_categories = {"non_ascii" if any(ord(char) > 127 for char in text) else "ascii_only"}
    for name, present in (
        ("zwnj", "\u200c" in text),
        ("persian_digits", any("\u06f0" <= char <= "\u06f9" for char in text)),
        ("arabic_indic_digits", any("\u0660" <= char <= "\u0669" for char in text)),
        ("combining_marks", any(unicodedata.category(char).startswith("M") for char in text)),
        ("supplementary_codepoints", any(ord(char) > 0xffff for char in text)),
    ):
        if present:
            unicode_categories.add(name)
    chunk_count = len(snapshot["points"])
    chunk_category = "up_to_three" if chunk_count <= 3 else "four" if chunk_count == 4 else "five_or_more"
    categories = {
        "commentary": {commentary}, "context": {"present" if context else "absent"},
        "date": {"present" if date else "absent"}, "unicode": unicode_categories,
        "chunk_count": {chunk_category},
    }
    # Exact context/date/chunk values add variety inside their broad categories.
    # Neither recency nor content quality is inferred from these values.
    variation = {dimension: frozenset(values) for dimension, values in categories.items()}
    if context:
        variation["context"] |= frozenset({"value:" + context})
    if date:
        variation["date"] |= frozenset({"value:" + date})
    variation["chunk_count"] |= frozenset({"count:" + str(chunk_count)})
    return variation, categories


def select_representative_sample(qualified_snapshots: Iterable[dict[str, Any]], *, sample_size: int = 100) -> dict[str, Any]:
    """Balance statuses, then cover within-status variation with stable ties.

    Default quotas are 20 for each of the five statuses. Absent or undersupplied
    quotas are filled from remaining records, favoring the least represented
    available status. Each choice maximizes unseen commentary/context/date/
    Unicode/chunk-count variation in that status; SHA-256 of ID breaks ties.
    Report unavailable source categories separately from categories omitted by
    a small sample. Never generate records to satisfy a quota or category.
    """
    if type(sample_size) is not int or sample_size < 1:
        raise ValueError("sample_size must be a positive integer")
    buckets: dict[int, list[str]] = {status: [] for status in _STATUSES}
    captures, variations, categories, hashes = {}, {}, {}, {}
    available_categories = {dimension: set() for dimension in _CATEGORY_UNIVERSE}
    for snapshot in qualified_snapshots:
        row = snapshot.get("sql")
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("qualified snapshots require a nonempty SQL ID")
        status = row.get("status_id")
        if type(status) is not int or status not in _STATUSES:
            raise ValueError("qualified snapshots require a known status code")
        if not isinstance(snapshot.get("points"), list):
            raise ValueError("qualified snapshots require the full point list")
        parent_id = row["id"]
        if parent_id in captures:
            raise ValueError("duplicate qualified SQL ID: " + parent_id)
        captures[parent_id] = snapshot
        variations[parent_id], categories[parent_id] = _variation(snapshot)
        hashes[parent_id] = hashlib.sha256(parent_id.encode("utf-8")).hexdigest()
        buckets[status].append(parent_id)
        for dimension, values in categories[parent_id].items():
            available_categories[dimension].update(values)
    available = {status: len(buckets[status]) for status in _STATUSES}
    quotas = {status: sample_size // 5 + int(index < sample_size % 5) for index, status in enumerate(_STATUSES)}
    counts = {status: 0 for status in _STATUSES}
    seen = {status: {dimension: set() for dimension in _CATEGORY_UNIVERSE} for status in _STATUSES}
    selected_ids = []
    selected_categories = {dimension: set() for dimension in _CATEGORY_UNIVERSE}

    def choose(status: int) -> None:
        parent_id = min(buckets[status], key=lambda candidate: (
            -sum(len(values - seen[status][dimension]) for dimension, values in variations[candidate].items()),
            hashes[candidate], candidate,
        ))
        buckets[status].remove(parent_id)
        selected_ids.append(parent_id)
        counts[status] += 1
        for dimension, values in variations[parent_id].items():
            seen[status][dimension].update(values)
        for dimension, values in categories[parent_id].items():
            selected_categories[dimension].update(values)

    # First honor each target quota; then use remaining qualified records.
    while len(selected_ids) < sample_size:
        eligible = [status for status in _STATUSES if buckets[status] and counts[status] < quotas[status]]
        if not eligible:
            break
        for status in eligible:
            if len(selected_ids) == sample_size:
                break
            choose(status)
    while len(selected_ids) < sample_size:
        eligible = [status for status in _STATUSES if buckets[status]]
        if not eligible:
            break
        choose(min(eligible, key=lambda status: (counts[status], status)))
    return {
        "requested": sample_size, "available": len(captures), "selected": len(selected_ids),
        "shortage": max(0, sample_size - len(selected_ids)),
        "status_quotas": quotas, "status_counts_available": available, "status_counts_selected": counts,
        "status_shortages": {status: max(0, quotas[status] - counts[status]) for status in _STATUSES},
        "unavailable_statuses": [status for status in _STATUSES if not available[status]],
        "available_categories": {dimension: sorted(values) for dimension, values in available_categories.items()},
        "selected_categories": {dimension: sorted(values) for dimension, values in selected_categories.items()},
        "unavailable_categories": {dimension: sorted(set(universe) - available_categories[dimension]) for dimension, universe in _CATEGORY_UNIVERSE.items()},
        "available_not_selected_categories": {dimension: sorted(values - selected_categories[dimension]) for dimension, values in available_categories.items()},
        "records": [copy.deepcopy(captures[parent_id]) for parent_id in selected_ids],
    }


__all__ = ["select_representative_sample"]
