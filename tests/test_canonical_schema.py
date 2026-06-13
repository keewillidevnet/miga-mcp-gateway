"""Schema-only tests for the Phase A canonical contract.

These exercise the canonical schema in isolation: construction, validators, and
the bridge to INFER's CorrelatedEvent. They use NO platform sample responses,
because the per-platform ADAPTERS are not built yet (blocked on real captured
JSON). The adapter round-trip tests will live alongside the adapters once those
samples arrive.

Run:  pytest tests/test_canonical_schema.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from miga_shared.canonical import (
    CanonicalEntity,
    CanonicalEvent,
    EntityType,
    NativeIdentifiers,
    ObservationPoint,
)
from miga_shared.models import CorrelatedEvent, PlatformType, SeverityLevel


def test_minimal_event_constructs_with_defaults():
    ev = CanonicalEvent(
        entity_ref="catalyst_center:abc",
        type="assurance_issue",
        source_platform=PlatformType.CATALYST_CENTER,
    )
    assert ev.severity is SeverityLevel.INFO
    assert ev.timestamp.tzinfo is not None  # never naive
    # flow fields default to None for a non-flow source
    assert ev.protocol is None and ev.dscp is None and ev.observation_point is None


def test_naive_timestamp_is_coerced_to_utc():
    ev = CanonicalEvent(
        entity_ref="ise:xyz",
        type="auth_event",
        source_platform=PlatformType.ISE,
        timestamp=datetime(2026, 6, 13, 12, 0, 0),  # naive
    )
    assert ev.timestamp.tzinfo == timezone.utc


def test_dscp_out_of_range_rejected():
    with pytest.raises(ValueError):
        CanonicalEvent(
            entity_ref="x:1",
            type="flow",
            source_platform=PlatformType.MERAKI,
            dscp=64,  # valid range is 0..63
        )


def test_observation_point_direction_validated():
    with pytest.raises(ValueError):
        ObservationPoint(interface="Gi0/1", direction="sideways")
    ok = ObservationPoint(interface="Gi0/1", direction="ingress")
    assert ok.direction == "ingress"


def test_to_correlated_event_maps_affected_entities_as_union():
    ev = CanonicalEvent(
        entity_ref="catalyst_center:dev-1",
        additional_entity_refs=["catalyst_center:dev-1", "ise:endpoint-9"],
        type="assurance_issue",
        source_platform=PlatformType.CATALYST_CENTER,
        severity=SeverityLevel.HIGH,
        source_record_ref="issues/12345",
        attributes={"issueName": "AP down"},
    )
    ce = ev.to_correlated_event()
    assert isinstance(ce, CorrelatedEvent)
    assert ce.source_platform is PlatformType.CATALYST_CENTER
    assert ce.event_type == "assurance_issue"
    assert ce.severity is SeverityLevel.HIGH
    # de-duplicated union, order preserved — this is what overlaps_with() needs
    assert ce.affected_entities == ["catalyst_center:dev-1", "ise:endpoint-9"]
    # source pointer + attributes preserved across the boundary
    assert ce.raw_data["source_record_ref"] == "issues/12345"
    assert ce.raw_data["attributes"]["issueName"] == "AP down"
    assert "flow" not in ce.raw_data  # nothing fabricated for a non-flow source


def test_correlated_event_overlaps_consumes_canonical_output():
    """The whole point of the bridge: two canonical events that share an entity
    inside the window must overlap once converted, since INFER keys on that."""
    base_ts = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
    a = CanonicalEvent(
        entity_ref="ise:endpoint-9", type="auth_failure",
        source_platform=PlatformType.ISE, timestamp=base_ts,
    ).to_correlated_event()
    b = CanonicalEvent(
        entity_ref="catalyst_center:dev-1",
        additional_entity_refs=["ise:endpoint-9"],
        type="assurance_issue",
        source_platform=PlatformType.CATALYST_CENTER, timestamp=base_ts,
    ).to_correlated_event()
    assert a.overlaps_with(b) is True


def test_entity_carries_native_identifiers_and_provisional_id():
    ident = NativeIdentifiers(
        hostname="sw-core-01", serial="FOC1234X5YZ", ip="10.1.1.1",
        extra={"netbox_id": "42"},
    )
    cid = CanonicalEntity.provisional_id(PlatformType.NETBOX, "42")
    ent = CanonicalEntity(
        canonical_id=cid,
        entity_type=EntityType.DEVICE,
        identifiers=ident,
        source_platform=PlatformType.NETBOX,
        source_record_ref="dcim/devices/42",
    )
    assert ent.canonical_id == "netbox:42"
    assert ent.identifiers.any_set() is True
    assert ent.identifiers.hostname == "sw-core-01"
    assert ent.identifiers.extra["netbox_id"] == "42"
    # NetBox has no flow/DSCP to contribute; nothing forced onto the entity.
    assert ent.identifiers.mac is None
