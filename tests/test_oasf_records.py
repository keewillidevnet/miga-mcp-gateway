"""Structural validation of the 9 OASF capability records.

These assert the records conform to the OASF Record shape (required fields,
typed skill/domain ids, RFC-3339 timestamp) and stay linked to the registry.
The numeric ids themselves were generated from the pinned OASF v1.0.4 catalog
(see MIGRATION.md); here we lock in their structural integrity offline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from miga_shared.registry import DEFAULT_REGISTRY_PATH, load_registry

ROOT = Path(DEFAULT_REGISTRY_PATH).parent.parent
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
REQUIRED = ["name", "version", "schema_version", "description", "authors", "created_at", "skills"]


def _records():
    for spec in load_registry():
        path = ROOT / spec.oasf_record
        yield spec, json.loads(path.read_text())


def test_one_record_per_registered_server():
    specs = load_registry()
    for spec in specs:
        assert (ROOT / spec.oasf_record).exists(), spec.name


@pytest.mark.parametrize("field", REQUIRED)
def test_required_fields_present(field):
    for spec, rec in _records():
        assert rec.get(field), f"{spec.name} missing {field}"


def test_schema_version_pinned():
    for _, rec in _records():
        assert rec["schema_version"] == "1.0.4"


def test_created_at_rfc3339():
    for spec, rec in _records():
        assert RFC3339.match(rec["created_at"]), f"{spec.name}: {rec['created_at']}"


def test_skills_and_domains_typed():
    for spec, rec in _records():
        assert rec["skills"], f"{spec.name} has no skills"
        for item in rec["skills"] + rec.get("domains", []):
            assert isinstance(item["name"], str) and item["name"]
            assert isinstance(item["id"], int) and item["id"] > 0


def test_record_links_back_to_registry():
    for spec, rec in _records():
        assert rec.get("annotations", {}).get("miga_registry_ref") == spec.name


def test_locator_points_to_source():
    for spec, rec in _records():
        locs = rec.get("locators", [])
        assert any(loc.get("type") == "source_code" and loc.get("urls") for loc in locs), spec.name


def test_modules_is_list():
    for _, rec in _records():
        assert isinstance(rec.get("modules", []), list)
