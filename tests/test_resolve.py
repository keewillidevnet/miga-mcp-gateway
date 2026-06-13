"""Tests for Phase B entity resolution.

Two directions, the way the roadmap frames it:
  - the REAL Phase A captures must NOT falsely merge (no over-merge on real data,
    since those sandboxes share no device), and
  - a CONSTRUCTED-overlap fixture (real shapes, identifiers deliberately aligned)
    must collapse one device across NetBox/Catalyst Center/ISE (catches misses),
    while leaving distinct devices separate (catches over-merge).

Plus unit coverage for normalization, anchoring, and the opt-in hostname key.

Run:  pytest tests/test_resolve.py
"""

from __future__ import annotations

import json
from pathlib import Path

from miga_shared.adapters.catalyst_center import catalyst_devices_response_to_entities
from miga_shared.adapters.ise import ise_endpoints_response_to_entities
from miga_shared.adapters.netbox import netbox_devices_response_to_entities
from miga_shared.canonical import CanonicalEntity, EntityType, NativeIdentifiers
from miga_shared.models import PlatformType
from miga_shared.resolve import (
    cluster_for,
    norm_mac,
    norm_serial,
    resolve_entities,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text())


def _real_device_entities() -> list[CanonicalEntity]:
    """The real captured device/endpoint entities across all three platforms."""
    return (
        netbox_devices_response_to_entities(_load("netbox_devices.json"))
        + catalyst_devices_response_to_entities(_load("catalyst_devices.json"))
        + ise_endpoints_response_to_entities(_load("ise_endpoints.json"))
    )


def _constructed_entities() -> list[CanonicalEntity]:
    doc = _load("constructed_overlap.json")
    return (
        netbox_devices_response_to_entities(doc["netbox_devices"])
        + catalyst_devices_response_to_entities(doc["catalyst_devices"])
        + ise_endpoints_response_to_entities(doc["ise_endpoints"])
    )


# --- normalization ---------------------------------------------------------


def test_mac_normalization_strips_separators_and_case():
    assert norm_mac("52:54:00:AB:CD:EF") == "525400abcdef"
    assert norm_mac("52-54-00-ab-cd-ef") == "525400abcdef"
    assert norm_mac("5254.00ab.cdef") == "525400abcdef"
    assert norm_mac("") is None
    assert norm_mac(None) is None


def test_serial_normalization_strips_and_uppercases():
    assert norm_serial("  fcw2245x0yz ") == "FCW2245X0YZ"
    assert norm_serial("") is None


# --- no false merges on REAL captures --------------------------------------


def test_real_captures_do_not_falsely_merge():
    entities = _real_device_entities()
    assert len(entities) == 5  # 2 NetBox devices + 2 Catalyst + 1 ISE
    resolved = resolve_entities(entities)
    # they share no normalized MAC/serial, so every one stays on its own
    assert len(resolved) == 5
    assert all(len(r.members) == 1 for r in resolved)
    assert all(not r.is_cross_platform for r in resolved)


# --- correct merges on the CONSTRUCTED overlap -----------------------------


def test_constructed_overlap_collapses_one_device_across_three_platforms():
    resolved = resolve_entities(_constructed_entities())
    # 5 inputs -> 3 resolved: {edge across 3 platforms}, core-sw-02, spare ISE
    assert len(resolved) == 3

    edge = cluster_for(resolved, "netbox:device:9001")
    assert edge is not None
    assert edge.is_cross_platform
    assert edge.members == sorted(
        [
            "netbox:device:9001",
            "catalyst_center:11111111-1111-1111-1111-111111111111",
            "ise:22222222-2222-2222-2222-222222222222",
        ]
    )
    assert edge.platforms == ["catalyst_center", "ise", "netbox"]


def test_anchor_is_netbox_and_identifiers_are_merged():
    edge = cluster_for(resolve_entities(_constructed_entities()), "netbox:device:9001")
    # NetBox wins the anchor, so the cluster adopts its id and entity_type
    assert edge.canonical_id == "netbox:device:9001"
    assert edge.entity_type is EntityType.DEVICE
    # merged view fills slots across platforms: NetBox hostname/serial,
    # Catalyst supplies the IP and MAC NetBox lacked
    assert edge.identifiers.serial == "FCW2245X0YZ"
    assert edge.identifiers.hostname == "edge-sw-01"
    assert edge.identifiers.ip == "10.99.0.1"
    assert edge.identifiers.mac == "52:54:00:AB:CD:EF"


def test_link_keys_are_reported_for_explainability():
    edge = cluster_for(resolve_entities(_constructed_entities()), "netbox:device:9001")
    # serial linked NetBox<->Catalyst; normalized MAC linked Catalyst<->ISE
    assert "serial:FCW2245X0YZ" in edge.match_keys
    assert "mac:525400abcdef" in edge.match_keys


def test_mac_case_difference_still_merges():
    # Catalyst MAC '52:54:00:AB:CD:EF' vs ISE '52:54:00:ab:cd:ef' -> same device
    edge = cluster_for(
        resolve_entities(_constructed_entities()), "ise:22222222-2222-2222-2222-222222222222"
    )
    assert "netbox:device:9001" in edge.members


def test_distinct_devices_do_not_over_merge():
    resolved = resolve_entities(_constructed_entities())
    core = cluster_for(resolved, "catalyst_center:33333333-3333-3333-3333-333333333333")
    spare = cluster_for(resolved, "ise:44444444-4444-4444-4444-444444444444")
    assert core.members == ["catalyst_center:33333333-3333-3333-3333-333333333333"]
    assert spare.members == ["ise:44444444-4444-4444-4444-444444444444"]


# --- the over-merge guard: hostname is opt-in ------------------------------


def _hostname_twins() -> list[CanonicalEntity]:
    # two genuinely different boxes that merely share a hostname ("sw1")
    a = CanonicalEntity(
        canonical_id="catalyst_center:aaa",
        entity_type=EntityType.DEVICE,
        identifiers=NativeIdentifiers(hostname="sw1", serial="SER-A", mac="00:00:00:00:00:0a"),
        source_platform=PlatformType.CATALYST_CENTER,
    )
    b = CanonicalEntity(
        canonical_id="netbox:device:1",
        entity_type=EntityType.DEVICE,
        identifiers=NativeIdentifiers(hostname="sw1", serial="SER-B", mac="00:00:00:00:00:0b"),
        source_platform=PlatformType.NETBOX,
    )
    return [a, b]


def test_shared_hostname_does_not_merge_by_default():
    resolved = resolve_entities(_hostname_twins())
    assert len(resolved) == 2  # different serial + MAC, so they stay separate


def test_hostname_merges_only_when_explicitly_opted_in():
    resolved = resolve_entities(_hostname_twins(), merge_keys=("mac", "serial", "hostname"))
    assert len(resolved) == 1  # now the shared hostname links them


# --- edge cases ------------------------------------------------------------


def test_entity_with_no_merge_keys_is_a_singleton_not_dropped():
    # NetBox PDU in the real sample has empty serial and no MAC -> no merge keys
    resolved = resolve_entities(_real_device_entities())
    pdu = cluster_for(resolved, "netbox:device:27")
    assert pdu is not None
    assert pdu.members == ["netbox:device:27"]


def test_empty_input_resolves_to_empty():
    assert resolve_entities([]) == []
