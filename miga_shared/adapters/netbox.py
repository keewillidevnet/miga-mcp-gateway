"""NetBox normalization adapter (Phase A, Collate).

STATUS: authored and TESTED AGAINST REAL CAPTURED SAMPLES from demo.netbox.dev
        (NetBox Community v4.6.2, captured 2026-06-13). NOT validated against a
        live production NetBox or any credentialed/customer instance.

Built against:
  - GET /api/dcim/devices/       -> CanonicalEntity (entity_type=device)
  - GET /api/ipam/ip-addresses/  -> CanonicalEntity (entity_type=ip_address)
  - GET /api/core/object-changes/ -> CanonicalEvent (change-log entry)

The change-log (GET /api/core/object-changes/) is NetBox's only event-shaped
data. Each entry records a create/update/delete on one object, so it maps to a
CanonicalEvent whose entity_ref uses the SAME provisional id that object's
entity adapter produces -- so Phase B can join the change event to the entity it
touched. NetBox change-log entries carry no severity, so severity defaults to
INFO (not invented).

NetBox is an inventory / source-of-truth system. It carries no traffic, ports,
protocol, app-classification, or DSCP, so the CanonicalEvent flow fields have no
NetBox source and are never populated here.
"""
from __future__ import annotations

from typing import Any, Optional

from ..canonical import CanonicalEntity, CanonicalEvent, EntityType, NativeIdentifiers
from ..models import PlatformType

_P = PlatformType.NETBOX


def _clean(s: Optional[str]) -> Optional[str]:
    """Empty/whitespace string -> None; otherwise the stripped string."""
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def _get(d: Any, *path: str) -> Any:
    """Safe nested lookup; returns None if any hop is missing or not a dict."""
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def netbox_device_to_entity(record: dict[str, Any]) -> CanonicalEntity:
    """Map one /api/dcim/devices/ result object to a CanonicalEntity.

    Identifier mapping (verified against the captured sample):
      hostname <- name
      serial   <- serial   (empty string -> None; sample device 27 has "")
      ip       <- primary_ip4.address or primary_ip.address  (SEE FLAG below)
      mac      <- None     (NetBox holds MACs on interfaces, not on the device
                            record; no device-level MAC exists in the sample.)
      uuid     <- None     (NetBox devices use an integer id, not a UUID.)
      ci       <- None     (NetBox is not a CMDB; no CI / sys_id field exists.)
      extra.netbox_id  <- id
      extra.asset_tag  <- asset_tag  (omitted when null, as on device 27)
      extra.site_slug  <- site.slug

    FLAG (unverified path): both sample devices have null primary IPs, so the
    primary_ip4.address mapping is implemented from the documented field name
    but is NOT exercised by the captured data. Capture a device that has a
    primary IP to validate the nested brief-IP shape before trusting it.
    """
    rid = record.get("id")
    native_key = f"device:{rid}"

    ip = _clean(_get(record, "primary_ip4", "address")) or _clean(
        _get(record, "primary_ip", "address")
    )

    extra: dict[str, str] = {}
    if rid is not None:
        extra["netbox_id"] = str(rid)
    asset_tag = _clean(record.get("asset_tag"))
    if asset_tag:
        extra["asset_tag"] = asset_tag
    site_slug = _clean(_get(record, "site", "slug"))
    if site_slug:
        extra["site_slug"] = site_slug

    identifiers = NativeIdentifiers(
        hostname=_clean(record.get("name")),
        serial=_clean(record.get("serial")),
        ip=ip,
        mac=None,
        ci=None,
        uuid=None,
        extra=extra,
    )

    attributes: dict[str, Any] = {
        "device_type": _get(record, "device_type", "model"),
        "manufacturer": _get(record, "device_type", "manufacturer", "name"),
        "role": _get(record, "role", "name"),
        "site": _get(record, "site", "name"),
        "status": _get(record, "status", "value"),
        "tenant": _get(record, "tenant", "name"),
        "created": record.get("created"),
        "last_updated": record.get("last_updated"),
    }

    return CanonicalEntity(
        canonical_id=CanonicalEntity.provisional_id(_P, native_key),
        entity_type=EntityType.DEVICE,
        identifiers=identifiers,
        source_platform=_P,
        source_record_ref=_clean(record.get("url")),
        attributes=attributes,
    )


def netbox_ipaddress_to_entity(record: dict[str, Any]) -> CanonicalEntity:
    """Map one /api/ipam/ip-addresses/ result object to a CanonicalEntity.

    Identifier mapping (verified against the captured sample):
      ip       <- address with the prefix length stripped
                  ("172.16.0.1/24" -> "172.16.0.1"); full value kept in
                  extra.cidr. (Splitting on "/" is the only transform; lossless
                  because the full CIDR is preserved.)
      hostname <- None  (an IP is not a host; the device it's assigned to is
                  recorded in extra.assigned_device for Phase B linking.)
      mac / uuid / ci <- None
      extra.netbox_id          <- id
      extra.cidr               <- address (with prefix)
      extra.vrf                <- vrf.name (if any)
      extra.assigned_device    <- assigned_object.device.name (omitted when the
                  IP is unassigned, as on sample IP 32)
      extra.assigned_interface <- assigned_object.name (if assigned)
    """
    rid = record.get("id")
    native_key = f"ip:{rid}"

    address = _clean(record.get("address"))  # e.g. "172.16.0.1/24"
    bare_ip = address.split("/")[0] if address else None

    extra: dict[str, str] = {}
    if rid is not None:
        extra["netbox_id"] = str(rid)
    if address:
        extra["cidr"] = address
    vrf = _clean(_get(record, "vrf", "name"))
    if vrf:
        extra["vrf"] = vrf
    assigned_dev = _clean(_get(record, "assigned_object", "device", "name"))
    if assigned_dev:
        extra["assigned_device"] = assigned_dev
    assigned_if = _clean(_get(record, "assigned_object", "name"))
    if assigned_if:
        extra["assigned_interface"] = assigned_if

    identifiers = NativeIdentifiers(
        hostname=None,
        serial=None,
        ip=bare_ip,
        mac=None,
        ci=None,
        uuid=None,
        extra=extra,
    )

    attributes: dict[str, Any] = {
        "family": _get(record, "family", "label"),
        "status": _get(record, "status", "value"),
        "dns_name": _clean(record.get("dns_name")),
        "assigned_object_type": record.get("assigned_object_type"),
        "created": record.get("created"),
        "last_updated": record.get("last_updated"),
    }

    return CanonicalEntity(
        canonical_id=CanonicalEntity.provisional_id(_P, native_key),
        entity_type=EntityType.IP_ADDRESS,
        identifiers=identifiers,
        source_platform=_P,
        source_record_ref=_clean(record.get("url")),
        attributes=attributes,
    )


def _results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the .results list from a NetBox paginated list response."""
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError(
            "expected a NetBox list response with a 'results' array; got keys: "
            + ", ".join(sorted(payload.keys()))
        )
    return results


def netbox_devices_response_to_entities(
    payload: dict[str, Any]
) -> list[CanonicalEntity]:
    return [netbox_device_to_entity(r) for r in _results(payload)]


def netbox_ipaddresses_response_to_entities(
    payload: dict[str, Any]
) -> list[CanonicalEntity]:
    return [netbox_ipaddress_to_entity(r) for r in _results(payload)]


# changed_object_type -> the native-key prefix the entity adapters use, so a
# change event's entity_ref matches the changed object's CanonicalEntity id.
# Only dcim.device appears in the captured sample; ipam.ipaddress is included by
# symmetry with netbox_ipaddress_to_entity (whose shape IS verified from the
# ip-addresses endpoint). Any other object type falls back to its raw type
# string, which is still deterministic and honest.
_OBJECT_KIND_PREFIX = {
    "dcim.device": "device",
    "ipam.ipaddress": "ip",
}


def _changed_object_native_key(object_type: Optional[str], object_id: Any) -> str:
    prefix = _OBJECT_KIND_PREFIX.get(object_type or "", object_type or "object")
    return f"{prefix}:{object_id}"


def netbox_changelog_to_event(record: dict[str, Any]) -> CanonicalEvent:
    """Map one /api/core/object-changes/ result object to a CanonicalEvent.

    Mapping (verified against the captured sample, which holds dcim.device
    'update' entries):
      type        <- "{changed_object_type}:{action.value}"  e.g.
                      "dcim.device:update"
      timestamp   <- time   (ISO-8601 with Z -> tz-aware UTC)
      entity_ref  <- provisional id of the changed object, matching the entity
                     adapters (changed device id 1 -> "netbox:device:1")
      severity    <- defaulted to INFO; NetBox change-log has no severity field
      source_record_ref <- url (the object-change record's own URL)
      attributes.changed_fields <- keys where prechange_data != postchange_data
      attributes.changes        <- {key: {from, to}} for exactly those keys
      attributes.{action,object_repr,object_name,user_name,request_id,message}

    FLAG (defensive, unverified): the sample only contains 'update' actions, so
    create (no prechange_data) and delete (no postchange_data) are handled
    defensively -- when either side is absent the diff is simply empty -- but
    those two paths are NOT exercised by real data yet.
    """
    action = _get(record, "action", "value")
    object_type = record.get("changed_object_type")
    object_id = record.get("changed_object_id")
    entity_ref = CanonicalEntity.provisional_id(
        _P, _changed_object_native_key(object_type, object_id)
    )

    pre = record.get("prechange_data")
    post = record.get("postchange_data")
    changed_fields: list[str] = []
    changes: dict[str, Any] = {}
    if isinstance(pre, dict) and isinstance(post, dict):
        for k in sorted(set(pre) | set(post)):
            if pre.get(k) != post.get(k):
                changed_fields.append(k)
                changes[k] = {"from": pre.get(k), "to": post.get(k)}

    attributes: dict[str, Any] = {
        "action": _get(record, "action", "label") or action,
        "changed_object_type": object_type,
        "changed_object_id": object_id,
        "object_repr": record.get("object_repr"),
        "object_name": _get(record, "changed_object", "name"),
        "user_name": _clean(record.get("user_name")),
        "request_id": _clean(record.get("request_id")),
        "message": _clean(record.get("message")),
        "changed_fields": changed_fields,
        "changes": changes,
    }

    event_type = (
        f"{object_type}:{action}"
        if object_type and action
        else (action or "object_change")
    )

    kwargs: dict[str, Any] = dict(
        entity_ref=entity_ref,
        type=event_type,
        source_platform=_P,
        source_record_ref=_clean(record.get("url")),
        attributes=attributes,
    )
    t = record.get("time")
    if t:
        kwargs["timestamp"] = t  # pydantic parses the ISO-8601 string
    return CanonicalEvent(**kwargs)


def netbox_changelog_response_to_events(
    payload: dict[str, Any]
) -> list[CanonicalEvent]:
    return [netbox_changelog_to_event(r) for r in _results(payload)]
