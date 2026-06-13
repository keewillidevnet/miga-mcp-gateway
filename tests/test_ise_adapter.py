"""Round-trip tests for the ISE adapter, using a REAL captured sample.

Fixture is the actual response from the DevNet reservable ISE sandbox
(ISE 3.x, OpenAPI on 443):
  fixtures/ise_endpoints.json  <- GET /api/v1/endpoint  (one seeded endpoint)

Asserts: real OpenAPI response -> valid CanonicalEntity with native identifiers
(MAC + UUID) attached; the session/auth event mapper stays blocked until a real
MnT (XML) sample exists. Does NOT prove anything against a live/production ISE.

Run:  pytest tests/test_ise_adapter.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miga_shared.adapters.ise import (
    ise_endpoint_to_entity,
    ise_endpoints_response_to_entities,
    ise_session_to_event,
)
from miga_shared.canonical import CanonicalEntity, EntityType
from miga_shared.models import PlatformType

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text())


# --- endpoints -------------------------------------------------------------


def test_endpoints_response_maps_every_result_to_valid_entity():
    entities = ise_endpoints_response_to_entities(_load("ise_endpoints.json"))
    assert len(entities) >= 1
    assert all(isinstance(e, CanonicalEntity) for e in entities)
    assert all(e.source_platform is PlatformType.ISE for e in entities)
    assert all(e.entity_type is EntityType.ENDPOINT for e in entities)


def test_seeded_endpoint_has_mac_and_uuid_attached():
    e = ise_endpoints_response_to_entities(_load("ise_endpoints.json"))[0]
    assert e.canonical_id == "ise:c1e83020-6750-11f1-bde9-ee64ce5f7161"
    assert e.identifiers.mac == "AA:BB:CC:00:11:22"
    assert e.identifiers.uuid == "c1e83020-6750-11f1-bde9-ee64ce5f7161"
    assert e.identifiers.extra["group_id"] == "aa0e8b20-8bff-11e6-996c-525400b48521"
    assert e.identifiers.any_set() is True
    assert e.source_record_ref == "c1e83020-6750-11f1-bde9-ee64ce5f7161"
    # honest nulls: ISE 'name' is the MAC (not a host), no IP/serial/CI on a
    # freshly added endpoint -- not invented
    assert e.identifiers.hostname is None
    assert e.identifiers.ip is None
    assert e.identifiers.serial is None
    assert e.identifiers.ci is None
    # the raw name is preserved as context, not forced into the hostname slot
    assert e.attributes["name"] == "AA:BB:CC:00:11:22"


def test_single_record_helper_matches_list_helper():
    payload = _load("ise_endpoints.json")
    single = ise_endpoint_to_entity(payload[0])
    via_list = ise_endpoints_response_to_entities(payload)[0]
    assert single.model_dump() == via_list.model_dump()


# --- session events (blocked) ----------------------------------------------


def test_session_event_is_blocked_until_a_real_mnt_sample_exists():
    with pytest.raises(NotImplementedError):
        ise_session_to_event({"acctSessionId": "whatever"})


# --- guards ----------------------------------------------------------------


def test_response_validation_rejects_a_non_array_payload():
    # ERS SearchResult is a dict, not the OpenAPI bare array -> rejected here
    with pytest.raises(ValueError):
        ise_endpoints_response_to_entities({"SearchResult": {"resources": []}})
