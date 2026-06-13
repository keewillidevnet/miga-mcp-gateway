"""Canonical schema for MIGA Phase A (Collate).

STATUS: AUTHORED and unit-tested against the schema itself.
        NOT validated against live platform APIs.

The per-platform adapters that POPULATE these models are intentionally NOT in
this module. They require real captured sample responses (Phase A hard rule:
never build an adapter on a guessed response shape). This file only locks the
contract those adapters will target.

Alignment, not a fork
----------------------
This schema reuses ``PlatformType`` and ``SeverityLevel`` from
``miga_shared.models`` and provides ``CanonicalEvent.to_correlated_event()``,
which emits the exact ``CorrelatedEvent`` that INFER's correlation engine
already consumes (source_platform / event_type / severity / timestamp /
affected_entities). ``CanonicalEvent`` is the producer-side normalized record;
``CorrelatedEvent`` stays INFER's consumption type. We extend; we do not run a
parallel schema.

Phase boundary
--------------
``canonical_id`` produced here is PROVISIONAL and platform-scoped
(e.g. ``"catalyst_center:<deviceUuid>"``). Phase B (entity resolution) is what
collapses several provisional entities across platforms onto one shared
canonical_id. Phase A only guarantees: a valid canonical record, with the
platform's native identifiers attached.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import CorrelatedEvent, PlatformType, SeverityLevel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Entity side
# ---------------------------------------------------------------------------


class EntityType(str, Enum):
    """The kinds of real things a CanonicalEntity can represent.

    Covers the roadmap's named set (device, interface, user, incident) plus the
    two the Phase A platforms actually emit (endpoint, ip_address).
    """

    DEVICE = "device"
    INTERFACE = "interface"
    USER = "user"
    ENDPOINT = "endpoint"
    INCIDENT = "incident"
    IP_ADDRESS = "ip_address"
    OTHER = "other"


class NativeIdentifiers(BaseModel):
    """Platform-native identifiers a CanonicalEntity was resolved from.

    Exactly the six named slots from the Phase A spec, plus ``extra`` for
    platform-specific ids that don't fit one of the six (e.g. a NetBox integer
    device id, an ISE endpoint id). Phase B collapses these across platforms.

    No format coercion is done here on purpose (e.g. MAC case/separators are
    left as the source emitted them). Canonicalizing identifier *formats* is a
    Phase B resolution concern; forcing a format now, before seeing real
    samples, would be guessing.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    hostname: str | None = None
    serial: str | None = None
    ip: str | None = None
    mac: str | None = None
    ci: str | None = None  # configuration-item id (e.g. CMDB sys_id)
    uuid: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)

    def any_set(self) -> bool:
        return any([self.hostname, self.serial, self.ip, self.mac, self.ci, self.uuid]) or bool(
            self.extra
        )


class CanonicalEntity(BaseModel):
    """The resolved identity of a real thing, with its native identifiers.

    At Phase A this is single-platform: one platform record -> one entity.
    Cross-platform merging happens in Phase B.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    canonical_id: str
    entity_type: EntityType
    identifiers: NativeIdentifiers = Field(default_factory=NativeIdentifiers)
    source_platform: PlatformType
    source_record_ref: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def provisional_id(platform: PlatformType, native_key: str) -> str:
        """Deterministic platform-scoped id for Phase A.

        ``native_key`` should be the most stable identifier the source gives
        (a device uuid, a serial, a NetBox id). Phase B may remap this.
        """
        return f"{platform.value}:{native_key}"


# ---------------------------------------------------------------------------
# Event side
# ---------------------------------------------------------------------------


class ObservationPoint(BaseModel):
    """Where a flow/telemetry event was observed.

    Null for inventory/auth sources (Catalyst Center, ISE, NetBox) — none of the
    three Phase A platforms reports a per-event capture interface/direction.
    Declared now for the flow-bearing platforms that come later
    (Meraki / ThousandEyes / SD-WAN).
    """

    interface: str | None = None
    direction: str | None = None  # "ingress" | "egress"

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, v: str | None) -> str | None:
        if v is not None and v not in ("ingress", "egress"):
            raise ValueError("direction must be 'ingress' or 'egress'")
        return v


class CanonicalEvent(BaseModel):
    """A normalized event with a stable entity reference and a source pointer.

    The flow fields (protocol / ports / app_classification / dscp /
    observation_point) are declared for the schema but populated ONLY where the
    source actually provides them. For the three Phase A platforms they stay
    ``None`` — see each adapter's note. They are not invented to look complete.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # --- core ---
    entity_ref: str  # canonical_id of the primary entity
    type: str  # normalized event type
    timestamp: datetime = Field(default_factory=_utcnow)
    source_platform: PlatformType
    source_record_ref: str | None = None  # pointer back to the source record
    severity: SeverityLevel = SeverityLevel.INFO
    attributes: dict[str, Any] = Field(default_factory=dict)
    additional_entity_refs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # --- flow / telemetry (populated only where the source provides it) ---
    protocol: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    app_classification: str | None = None
    dscp: int | None = None
    observation_point: ObservationPoint | None = None

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        # Mirror CorrelatedEvent's tz-aware UTC convention; never store naive.
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @field_validator("dscp")
    @classmethod
    def _dscp_range(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 63):
            raise ValueError("dscp must be a 6-bit codepoint in 0..63")
        return v

    def all_entity_refs(self) -> list[str]:
        """entity_ref + additional refs, de-duplicated, order preserved."""
        seen: set[str] = set()
        out: list[str] = []
        for r in [self.entity_ref, *self.additional_entity_refs]:
            if r and r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def to_correlated_event(self) -> CorrelatedEvent:
        """Bridge to the type INFER's engine already consumes.

        ``affected_entities`` is the union of entity_ref + additional refs,
        which is exactly the field ``CorrelatedEvent.overlaps_with()``
        intersects. The source-record pointer, the normalized attributes, and
        any populated flow fields are preserved under ``raw_data`` so nothing is
        lost crossing the boundary.
        """
        raw: dict[str, Any] = {"attributes": self.attributes}
        if self.source_record_ref is not None:
            raw["source_record_ref"] = self.source_record_ref

        flow = {
            k: v
            for k, v in {
                "protocol": self.protocol,
                "src_port": self.src_port,
                "dst_port": self.dst_port,
                "app_classification": self.app_classification,
                "dscp": self.dscp,
                "observation_point": (
                    self.observation_point.model_dump() if self.observation_point else None
                ),
            }.items()
            if v is not None
        }
        if flow:
            raw["flow"] = flow

        return CorrelatedEvent(
            source_platform=self.source_platform,
            event_type=self.type,
            severity=self.severity,
            timestamp=self.timestamp,
            affected_entities=self.all_entity_refs(),
            raw_data=raw,
            tags=list(self.tags),
        )
