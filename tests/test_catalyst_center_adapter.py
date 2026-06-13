"""Round-trip tests for the Catalyst Center adapter, using REAL captured samples.

Fixtures are the actual responses from the DevNet always-on sandbox
sandboxdnac.cisco.com:
  fixtures/catalyst_devices.json  <- GET /dna/intent/api/v1/network-device?limit=2
  fixtures/catalyst_issues.json   <- GET /dna/intent/api/v1/issues  (came back empty)

These assert: real device response -> valid CanonicalEntity records with native
identifiers attached; and that the empty issues envelope yields [] while the
per-issue mapper stays blocked until a non-empty sample exists. They do NOT
prove anything against a live/production Catalyst Center.

Run:  pytest tests/test_catalyst_center_adapter.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from miga_shared.adapters.catalyst_center import (
    catalyst_device_to_entity,
    catalyst_devices_response_to_entities,
    catalyst_issue_to_event,
    catalyst_issues_response_to_events,
)
from miga_shared.canonical import CanonicalEntity, EntityType
from miga_shared.models import PlatformType

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# --- devices ---------------------------------------------------------------

def test_devices_response_maps_every_result_to_valid_entity():
    entities = catalyst_devices_response_to_entities(_load("catalyst_devices.json"))
    assert len(entities) == 2
    assert all(isinstance(e, CanonicalEntity) for e in entities)
    assert all(e.source_platform is PlatformType.CATALYST_CENTER for e in entities)
    assert all(e.entity_type is EntityType.DEVICE for e in entities)


def test_known_device_has_all_native_identifiers_attached():
    e = catalyst_devices_response_to_entities(_load("catalyst_devices.json"))[0]
    assert e.canonical_id == "catalyst_center:aa754801-8895-41e8-8ca5-27ee415c9c42"
    assert e.identifiers.hostname == "sw1"
    assert e.identifiers.serial == "CML12345UAD"
    assert e.identifiers.ip == "10.10.20.175"
    assert e.identifiers.mac == "52:54:00:02:19:54"
    assert e.identifiers.uuid == "aa754801-8895-41e8-8ca5-27ee415c9c42"
    # Catalyst Center is not a CMDB -> no CI, not invented
    assert e.identifiers.ci is None
    assert e.identifiers.any_set() is True
    # source handle is the device's own id (no per-record URL in the response)
    assert e.source_record_ref == "aa754801-8895-41e8-8ca5-27ee415c9c42"
    # context lives in attributes, not forced into identifier slots
    assert e.attributes["role"] == "ACCESS"
    assert e.attributes["platform_id"] == "C9KV-UADP-8P"
    assert e.attributes["software_version"] == "17.12.1prd9"


def test_second_device_identifiers():
    e = catalyst_devices_response_to_entities(_load("catalyst_devices.json"))[1]
    assert e.identifiers.hostname == "sw2"
    assert e.identifiers.serial == "CML12345"
    assert e.identifiers.ip == "10.10.20.176"
    assert e.identifiers.mac == "52:54:00:07:29:d0"
    assert e.canonical_id == "catalyst_center:5a105585-b595-4b87-a01d-fd057a54abd4"


def test_single_record_helper_matches_list_helper():
    payload = _load("catalyst_devices.json")
    single = catalyst_device_to_entity(payload["response"][0])
    via_list = catalyst_devices_response_to_entities(payload)[0]
    assert single.model_dump() == via_list.model_dump()


# --- issues (events) -------------------------------------------------------

def test_empty_issues_envelope_yields_no_events():
    # the real captured /issues response is {"response": [], "totalCount": "0"}
    events = catalyst_issues_response_to_events(_load("catalyst_issues.json"))
    assert events == []


def test_per_issue_mapping_is_blocked_until_a_real_issue_object_exists():
    with pytest.raises(NotImplementedError):
        catalyst_issue_to_event({"issueId": "whatever"})


# --- guards ----------------------------------------------------------------

def test_response_validation_rejects_a_payload_without_response_list():
    with pytest.raises(ValueError):
        catalyst_devices_response_to_entities({"version": "1.0"})
