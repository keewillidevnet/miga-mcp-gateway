"""Round-trip tests for the NetBox adapter, using REAL captured samples.

Fixtures are the actual responses pulled from demo.netbox.dev (v4.6.2):
  fixtures/netbox_devices.json      <- GET /api/dcim/devices/?limit=2
  fixtures/netbox_ipaddresses.json  <- GET /api/ipam/ip-addresses/?limit=2

These assert the contract: real response -> valid CanonicalEntity records, and
a known device -> a CanonicalEntity with its native identifiers attached. They
do NOT prove anything against a live/production NetBox.

Run:  pytest tests/test_netbox_adapter.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from miga_shared.adapters.netbox import (
    netbox_changelog_response_to_events,
    netbox_changelog_to_event,
    netbox_device_to_entity,
    netbox_devices_response_to_entities,
    netbox_ipaddresses_response_to_entities,
)
from miga_shared.canonical import CanonicalEntity, CanonicalEvent, EntityType
from miga_shared.models import PlatformType, SeverityLevel

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# --- devices ---------------------------------------------------------------


def test_devices_response_maps_every_result_to_valid_entity():
    entities = netbox_devices_response_to_entities(_load("netbox_devices.json"))
    assert len(entities) == 2
    assert all(isinstance(e, CanonicalEntity) for e in entities)
    assert all(e.source_platform is PlatformType.NETBOX for e in entities)
    assert all(e.entity_type is EntityType.DEVICE for e in entities)


def test_known_device_has_its_identifiers_attached():
    e = netbox_devices_response_to_entities(_load("netbox_devices.json"))[0]
    assert e.canonical_id == "netbox:device:138"
    assert e.identifiers.hostname == "dmi01-akron-k8s01"
    assert e.identifiers.serial == "ABC123"
    assert e.identifiers.extra["netbox_id"] == "138"
    assert e.identifiers.extra["asset_tag"] == "TSDBD3DS"
    assert e.identifiers.extra["site_slug"] == "dm-akron"
    assert e.identifiers.any_set() is True
    assert e.source_record_ref == "https://demo.netbox.dev/api/dcim/devices/138/"
    # NetBox truth, not invented: no device-level MAC / UUID / CI, and both
    # sample devices have null primary IPs.
    assert e.identifiers.mac is None
    assert e.identifiers.uuid is None
    assert e.identifiers.ci is None
    assert e.identifiers.ip is None
    # context preserved in attributes, not forced into identifier slots
    assert e.attributes["manufacturer"] == "Dell"
    assert e.attributes["role"] == "Application Server"


def test_empty_serial_becomes_none_and_missing_asset_tag_is_omitted():
    # sample device 27 has serial "" and asset_tag null
    e = netbox_devices_response_to_entities(_load("netbox_devices.json"))[1]
    assert e.canonical_id == "netbox:device:27"
    assert e.identifiers.serial is None
    assert "asset_tag" not in e.identifiers.extra
    assert e.attributes["tenant"] == "Dunder-Mifflin, Inc."


# --- ip addresses ----------------------------------------------------------


def test_ip_address_strips_prefix_and_links_assigned_device():
    entities = netbox_ipaddresses_response_to_entities(_load("netbox_ipaddresses.json"))
    assert len(entities) == 2
    first = entities[0]
    assert first.entity_type is EntityType.IP_ADDRESS
    assert first.canonical_id == "netbox:ip:31"
    assert first.identifiers.ip == "172.16.0.1"  # prefix stripped
    assert first.identifiers.extra["cidr"] == "172.16.0.1/24"  # full kept
    assert first.identifiers.extra["vrf"] == "Alpha"
    assert first.identifiers.extra["assigned_device"] == "dmi01-akron-rtr01"
    assert first.identifiers.extra["assigned_interface"] == "GigabitEthernet0/0/0"


def test_unassigned_ip_omits_assignment_fields():
    # sample IP 32 has assigned_object null
    second = netbox_ipaddresses_response_to_entities(_load("netbox_ipaddresses.json"))[1]
    assert second.canonical_id == "netbox:ip:32"
    assert second.identifiers.ip == "172.16.0.2"
    assert "assigned_device" not in second.identifiers.extra


# --- change log (events) ---------------------------------------------------


def test_changelog_response_maps_every_result_to_valid_event():
    events = netbox_changelog_response_to_events(_load("netbox_changelog.json"))
    assert len(events) == 2
    assert all(isinstance(e, CanonicalEvent) for e in events)
    assert all(e.source_platform is PlatformType.NETBOX for e in events)
    # no severity field in NetBox change-log -> default INFO, not invented
    assert all(e.severity is SeverityLevel.INFO for e in events)
    # NetBox is not a flow source -> flow fields stay null
    assert all(e.protocol is None and e.dscp is None for e in events)


def test_device_update_event_points_at_the_device_entity():
    ev = netbox_changelog_response_to_events(_load("netbox_changelog.json"))[0]
    assert ev.type == "dcim.device:update"
    assert ev.source_record_ref == ("https://demo.netbox.dev/api/core/object-changes/1200/")
    assert ev.timestamp == datetime(2026, 6, 13, 15, 38, 35, 765772, tzinfo=timezone.utc)
    # entity_ref is exactly the id the device entity adapter makes for device 1,
    # so Phase B can join this change to the entity it touched
    assert ev.entity_ref == "netbox:device:1"
    assert ev.entity_ref == CanonicalEntity.provisional_id(PlatformType.NETBOX, "device:1")


def test_changed_fields_are_a_real_diff_of_pre_and_post():
    events = netbox_changelog_response_to_events(_load("netbox_changelog.json"))
    # record 1200: only 'comments' differs between pre/post
    assert events[0].attributes["changed_fields"] == ["comments"]
    chg = events[0].attributes["changes"]["comments"]
    assert chg["from"] != chg["to"]
    # record 1199: only 'primary_ip6' differs (its comments are identical
    # pre/post -- it was record 1200 that edited comments)
    assert events[1].attributes["changed_fields"] == ["primary_ip6"]
    assert events[1].attributes["changes"]["primary_ip6"] == {"from": None, "to": 181}


def test_change_event_bridges_to_correlated_event():
    ev = netbox_changelog_response_to_events(_load("netbox_changelog.json"))[0]
    ce = ev.to_correlated_event()
    assert ce.source_platform is PlatformType.NETBOX
    assert ce.event_type == "dcim.device:update"
    assert ce.affected_entities == ["netbox:device:1"]
    assert ce.raw_data["source_record_ref"].endswith("/object-changes/1200/")


def test_single_changelog_helper_matches_list_helper():
    payload = _load("netbox_changelog.json")
    single = netbox_changelog_to_event(payload["results"][0])
    via_list = netbox_changelog_response_to_events(payload)[0]
    assert single.model_dump() == via_list.model_dump()


# --- guards ----------------------------------------------------------------


def test_list_validation_rejects_a_non_list_payload():
    with pytest.raises(ValueError):
        netbox_devices_response_to_entities({"detail": "Not found."})


def test_single_record_helper_matches_list_helper():
    payload = _load("netbox_devices.json")
    single = netbox_device_to_entity(payload["results"][0])
    via_list = netbox_devices_response_to_entities(payload)[0]
    assert single.model_dump() == via_list.model_dump()
