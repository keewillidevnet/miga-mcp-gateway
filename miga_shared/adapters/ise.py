"""Cisco ISE normalization adapter (Phase A, Collate).

STATUS: authored and TESTED AGAINST A REAL CAPTURED SAMPLE from the DevNet
        reservable ISE sandbox (ISE 3.x, node 10.10.20.77, captured 2026-06-13).
        NOT validated against a live production ISE.

Built against:
  - GET /api/v1/endpoint  (ISE OpenAPI, port 443) -> CanonicalEntity
    (entity_type=endpoint)

Transport note: this is ISE's OpenAPI, which returns a BARE JSON array of
endpoint objects. It is NOT the ERS API (port 9060, SearchResult-wrapped) --
ERS was disabled on the sandbox, so the ERS shape is intentionally NOT mapped
here. If a future capture uses ERS, its wrapper differs and needs its own
parser.

Event mapping (auth / session) is intentionally NOT implemented. ISE's session
and authentication events come from the separate MnT (Monitoring) API, which
returns XML rather than JSON, and an idle sandbox with no live authentications
has no sessions to capture. catalyst-style: ise_session_to_event() raises until
a real MnT sample exists, rather than guess an XML shape we never observed.

ISE is an identity/policy source, not a flow exporter, so the CanonicalEvent
flow fields (protocol/ports/app/dscp/observation_point) have no ISE source.
(Note: the endpoint object HAS a "protocol" field, but it is an endpoint
attribute, not a flow protocol, and it is not mapped onto any flow field.)
"""
from __future__ import annotations

from typing import Any, Optional

from ..canonical import CanonicalEntity, CanonicalEvent, EntityType, NativeIdentifiers
from ..models import PlatformType

_P = PlatformType.ISE


def _clean(s: Optional[Any]) -> Optional[str]:
    """Empty/whitespace string -> None; otherwise the stripped string."""
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def ise_endpoint_to_entity(record: dict[str, Any]) -> CanonicalEntity:
    """Map one /api/v1/endpoint object (ISE OpenAPI) to a CanonicalEntity.

    Identifier mapping (verified against the captured sample):
      mac      <- mac                ("AA:BB:CC:00:11:22"; kept as-is, no
                  case/separator coercion -- canonicalization is Phase B)
      uuid     <- id                 (ISE endpoint id is a UUID)
      ip       <- ipAddress          (null on the freshly-added sample endpoint)
      serial   <- serialNumber       (null on the sample)
      hostname <- None               (ISE 'name' equals the MAC for an endpoint,
                  not a hostname, so it is NOT mapped into the hostname slot;
                  the raw name is preserved in attributes.name)
      ci       <- None               (ISE is not a CMDB)
      extra.group_id   <- groupId    (endpoint identity-group id)
      extra.profile_id <- profileId  (omitted when empty, as on the sample)

    source_record_ref: the OpenAPI array carries no per-record URL, so the
    endpoint's own id is used as the stable handle (same choice as Catalyst).
    """
    rid = _clean(record.get("id"))
    mac = _clean(record.get("mac"))
    native_key = rid or mac or "unknown"

    extra: dict[str, str] = {}
    group_id = _clean(record.get("groupId"))
    if group_id:
        extra["group_id"] = group_id
    profile_id = _clean(record.get("profileId"))
    if profile_id:
        extra["profile_id"] = profile_id

    identifiers = NativeIdentifiers(
        hostname=None,
        serial=_clean(record.get("serialNumber")),
        ip=_clean(record.get("ipAddress")),
        mac=mac,
        ci=None,
        uuid=rid,
        extra=extra,
    )

    attributes: dict[str, Any] = {
        "name": record.get("name"),
        "description": _clean(record.get("description")),
        "vendor": record.get("vendor"),
        "device_type": record.get("deviceType"),
        "product_id": record.get("productId"),
        "profile_id": record.get("profileId"),
        "group_id": record.get("groupId"),
        "portal_user": _clean(record.get("portalUser")),
        "static_group_assignment": record.get("staticGroupAssignment"),
        "static_profile_assignment": record.get("staticProfileAssignment"),
    }

    return CanonicalEntity(
        canonical_id=CanonicalEntity.provisional_id(_P, native_key),
        entity_type=EntityType.ENDPOINT,
        identifiers=identifiers,
        source_platform=_P,
        source_record_ref=rid,
        attributes=attributes,
    )


def ise_endpoints_response_to_entities(
    payload: Any,
) -> list[CanonicalEntity]:
    """Map an ISE OpenAPI /api/v1/endpoint response to entities.

    OpenAPI returns a bare JSON array. (ERS would return a SearchResult dict;
    that shape was not captured and is not handled here.)
    """
    if not isinstance(payload, list):
        raise ValueError(
            "expected ISE OpenAPI /api/v1/endpoint response to be a JSON array; "
            "got " + type(payload).__name__
            + " (ERS SearchResult wrapper is not handled -- ERS was disabled)"
        )
    return [ise_endpoint_to_entity(r) for r in payload]


def ise_session_to_event(record: dict[str, Any]) -> CanonicalEvent:
    """PENDING: build against a real ISE MnT session/auth sample.

    ISE auth/session events come from the MnT (Monitoring) API, which returns
    XML, not JSON, and the idle sandbox had no live sessions to capture. The
    per-field shape (calling-station-id/MAC, NAS, auth status, timestamps) must
    not be guessed from memory, and the XML parsing differs from the JSON
    adapters. Capture a real MnT response (with at least one active session) and
    this gets built then.
    """
    raise NotImplementedError(
        "ise_session_to_event needs a real ISE MnT (XML) session sample; the "
        "sandbox had no live sessions and MnT was not captured"
    )
