"""Catalyst Center normalization adapter (Phase A, Collate).

STATUS: authored and TESTED AGAINST REAL CAPTURED SAMPLES from the DevNet
        always-on sandbox sandboxdnac.cisco.com (captured 2026-06-13). NOT
        validated against a live production Catalyst Center.

Built against:
  - GET /dna/intent/api/v1/network-device -> CanonicalEntity (entity_type=device)
  - GET /dna/intent/api/v1/issues         -> CanonicalEvent  (SEE BELOW)

Both endpoints wrap their payload in {"response": [...], "version": "1.0"}
(issues also carries "totalCount"). The device list is fully mapped from real
data. The issues list came back EMPTY in the capture ({"response": []}), so:
  - catalyst_issues_response_to_events() works on the verified envelope and
    returns [] for the empty real sample, but
  - catalyst_issue_to_event() raises NotImplementedError, because no real issue
    OBJECT was captured and its per-field shape must not be guessed. Capture a
    non-empty /issues response (a sandbox with an open assurance issue) and the
    per-issue mapping gets built then.

Catalyst Center is an assurance/inventory controller, not a flow exporter, so
the CanonicalEvent flow fields (protocol/ports/app/dscp/observation_point) have
no source here and stay null.
"""

from __future__ import annotations

from typing import Any

from ..canonical import CanonicalEntity, CanonicalEvent, EntityType, NativeIdentifiers
from ..models import PlatformType

_P = PlatformType.CATALYST_CENTER


def _clean(s: Any | None) -> str | None:
    """Empty/whitespace string -> None; otherwise the stripped string."""
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def catalyst_device_to_entity(record: dict[str, Any]) -> CanonicalEntity:
    """Map one /dna/intent/api/v1/network-device result to a CanonicalEntity.

    Identifier mapping (verified against the captured sample):
      hostname <- hostname               ("sw1")
      serial   <- serialNumber           ("CML12345UAD")
      ip       <- managementIpAddress    ("10.10.20.175")
      mac      <- macAddress             ("52:54:00:02:19:54"; kept as-is, no
                  case/separator coercion -- format canonicalization is Phase B)
      uuid     <- instanceUuid           (a genuine UUID; id == instanceUuid in
                  the sample)
      ci       <- None                   (Catalyst Center is not a CMDB)
      extra.instance_tenant_id <- instanceTenantId (if present)

    source_record_ref: Catalyst Center's inventory response has no per-record
    URL field, so the device's own id (instanceUuid) is used as the stable
    handle back to the record rather than constructing a URL we didn't observe.
    """
    native_key = _clean(record.get("instanceUuid")) or _clean(record.get("id"))

    extra: dict[str, str] = {}
    tenant = _clean(record.get("instanceTenantId"))
    if tenant:
        extra["instance_tenant_id"] = tenant

    identifiers = NativeIdentifiers(
        hostname=_clean(record.get("hostname")),
        serial=_clean(record.get("serialNumber")),
        ip=_clean(record.get("managementIpAddress")),
        mac=_clean(record.get("macAddress")),
        ci=None,
        uuid=_clean(record.get("instanceUuid")),
        extra=extra,
    )

    attributes: dict[str, Any] = {
        "platform_id": record.get("platformId"),
        "type": record.get("type"),
        "series": record.get("series"),
        "family": record.get("family"),
        "role": record.get("role"),
        "software_type": record.get("softwareType"),
        "software_version": record.get("softwareVersion"),
        "vendor": record.get("vendor"),
        "reachability_status": record.get("reachabilityStatus"),
        "management_state": record.get("managementState"),
        "collection_status": record.get("collectionStatus"),
        "up_time": record.get("upTime"),
        "uptime_seconds": record.get("uptimeSeconds"),
        "boot_date_time": record.get("bootDateTime"),
        "last_updated": record.get("lastUpdated"),
    }

    return CanonicalEntity(
        canonical_id=CanonicalEntity.provisional_id(_P, native_key or "unknown"),
        entity_type=EntityType.DEVICE,
        identifiers=identifiers,
        source_platform=_P,
        source_record_ref=native_key,
        attributes=attributes,
    )


def _response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the .response list from a Catalyst Center wrapped response."""
    items = payload.get("response")
    if not isinstance(items, list):
        raise ValueError(
            "expected a Catalyst Center response with a 'response' array; got "
            "keys: " + ", ".join(sorted(payload.keys()))
        )
    return items


def catalyst_devices_response_to_entities(payload: dict[str, Any]) -> list[CanonicalEntity]:
    return [catalyst_device_to_entity(r) for r in _response(payload)]


def catalyst_issue_to_event(issue: dict[str, Any]) -> CanonicalEvent:
    """PENDING: build against a non-empty /dna/intent/api/v1/issues sample.

    The captured /issues response was empty ({"response": []}), so no real issue
    object exists to map. The per-issue field names (issueId, name, priority,
    category, status, device/client entity refs, timestamps) must NOT be guessed
    from memory. Capture a sandbox that has an open assurance issue and this gets
    built: name/category -> type, priority -> severity, the implicated device ->
    entity_ref (matching catalyst_device_to_entity's canonical_id), timestamp ->
    timestamp.
    """
    raise NotImplementedError(
        "catalyst_issue_to_event needs a non-empty /issues sample; the captured "
        "response had response=[] so the per-issue shape is unknown"
    )


def catalyst_issues_response_to_events(payload: dict[str, Any]) -> list[CanonicalEvent]:
    """Map a /issues response to events.

    Works on the verified envelope: the empty real sample yields []. If the list
    is non-empty this will raise via catalyst_issue_to_event until that mapping
    is built against a real issue object.
    """
    return [catalyst_issue_to_event(i) for i in _response(payload)]
