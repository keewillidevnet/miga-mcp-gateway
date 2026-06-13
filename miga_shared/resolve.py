"""Phase B — entity resolution.

Collapses the platform-scoped ``CanonicalEntity`` records that Phase A produces
onto one resolved entity per real-world thing, by matching their native
identifiers across platforms.

STATUS: authored and tested against (a) the REAL Phase A captures — asserting
they do NOT spuriously merge, since those independent sandboxes share no device
— and (b) a CONSTRUCTED-overlap fixture in the real response shapes, with one
device's identifiers deliberately aligned across NetBox / Catalyst Center / ISE
to exercise merging. The constructed overlap is explicitly synthetic: the only
free real cross-platform overlap is the Catalyst Center + ISE SDA pairing, which
was not captured here, so the positive-merge case is seeded, not observed.

Matching
--------
- Strong cross-platform keys: MAC and serial (normalized). Two entities that
  share either are merged (transitively: NetBox--serial-->Catalyst--mac-->ISE
  collapses to one).
- Identifier-format canonicalization happens HERE (deferred from Phase A): MAC
  is lowercased with all separators stripped; serial is stripped + uppercased.
- Per-platform ids (uuid, the NetBox integer id) are NOT cross-platform keys --
  an ISE UUID can't equal a Catalyst UUID -- so they never cause a merge.
- hostname and ip are available as optional keys but OFF by default: hostnames
  collide ("sw1" in two sites) and IPs get reassigned, so merging on them
  over-merges. They corroborate; they don't decide.

Anchoring
---------
A resolved cluster adopts its canonical_id from the highest-priority platform
present (default NetBox > Catalyst Center > ISE > anything else), making the
inventory/source-of-truth system the identity anchor, per the roadmap. An entity
known to only one platform keeps that platform's provisional id.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from .canonical import CanonicalEntity, EntityType, NativeIdentifiers
from .models import PlatformType

# Keys that, when shared, cause a merge. MAC and serial are strong; hostname/ip
# are opt-in (see module docstring).
DEFAULT_MERGE_KEYS: tuple[str, ...] = ("mac", "serial")

# Identity-anchor order: the cluster's canonical_id comes from the earliest
# platform in this tuple that is present in the cluster.
DEFAULT_ANCHOR_PRIORITY: tuple[PlatformType, ...] = (
    PlatformType.NETBOX,
    PlatformType.CATALYST_CENTER,
    PlatformType.ISE,
)

_NON_HEX = re.compile(r"[^0-9a-f]")


# ---------------------------------------------------------------------------
# Identifier normalization (the Phase B canonicalization deferred from Phase A)
# ---------------------------------------------------------------------------


def norm_mac(v: str | None) -> str | None:
    """Lowercase and strip all non-hex separators: '52:54:00:AB:CD:EF' ->
    '525400abcdef'. Returns None if nothing hex-like remains."""
    if not v:
        return None
    s = _NON_HEX.sub("", v.lower())
    return s or None


def norm_serial(v: str | None) -> str | None:
    """Strip + uppercase. Returns None for empty."""
    if not v:
        return None
    s = v.strip().upper()
    return s or None


def norm_hostname(v: str | None) -> str | None:
    """Strip + lowercase. (Not a default merge key.)"""
    if not v:
        return None
    s = v.strip().lower()
    return s or None


def norm_ip(v: str | None) -> str | None:
    """Strip. (Not a default merge key.)"""
    if not v:
        return None
    return v.strip() or None


_NORMALIZERS = {
    "mac": norm_mac,
    "serial": norm_serial,
    "hostname": norm_hostname,
    "ip": norm_ip,
}


def identity_keys(
    entity: CanonicalEntity, kinds: Iterable[str] = DEFAULT_MERGE_KEYS
) -> set[tuple[str, str]]:
    """The normalized (kind, value) match keys an entity contributes."""
    ident = entity.identifiers
    out: set[tuple[str, str]] = set()
    for kind in kinds:
        norm = _NORMALIZERS.get(kind)
        if norm is None:
            continue
        val = norm(getattr(ident, kind, None))
        if val:
            out.add((kind, val))
    return out


# ---------------------------------------------------------------------------
# Resolved entity
# ---------------------------------------------------------------------------


class ResolvedEntity(BaseModel):
    """One real-world thing, resolved from one or more platform entities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    canonical_id: str  # adopted from the anchor platform
    entity_type: EntityType
    members: list[str]  # provisional canonical_ids that merged
    platforms: list[str]  # distinct source platforms represented
    identifiers: NativeIdentifiers  # merged identifier view
    match_keys: list[str] = Field(default_factory=list)  # keys that linked it

    @property
    def is_cross_platform(self) -> bool:
        return len(self.platforms) > 1


# ---------------------------------------------------------------------------
# Union-find
# ---------------------------------------------------------------------------


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent: list[int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def _platform_rank(p: PlatformType, anchor_priority: tuple[PlatformType, ...]) -> int:
    try:
        return anchor_priority.index(p)
    except ValueError:
        return len(anchor_priority)


def _build_resolved(
    members: list[CanonicalEntity],
    member_keys: list[set[tuple[str, str]]],
    anchor_priority: tuple[PlatformType, ...],
) -> ResolvedEntity:
    # Order by anchor priority, then canonical_id for determinism.
    order = sorted(
        range(len(members)),
        key=lambda i: (
            _platform_rank(members[i].source_platform, anchor_priority),
            members[i].canonical_id,
        ),
    )
    ordered = [members[i] for i in order]
    anchor = ordered[0]

    def pick(attr: str) -> str | None:
        for e in ordered:
            v = getattr(e.identifiers, attr)
            if v:
                return v
        return None

    # extra: merge low-to-high priority so the anchor wins on key conflicts.
    extra: dict[str, str] = {}
    for e in reversed(ordered):
        extra.update(e.identifiers.extra)

    merged = NativeIdentifiers(
        hostname=pick("hostname"),
        serial=pick("serial"),
        ip=pick("ip"),
        mac=pick("mac"),
        ci=pick("ci"),
        uuid=pick("uuid"),
        extra=extra,
    )

    # A key "linked" the cluster if it appears in two or more members.
    counts: Counter[tuple[str, str]] = Counter()
    for ks in member_keys:
        counts.update(ks)
    match_keys = sorted(f"{kind}:{val}" for (kind, val), n in counts.items() if n >= 2)

    return ResolvedEntity(
        canonical_id=anchor.canonical_id,
        entity_type=anchor.entity_type,
        members=sorted(e.canonical_id for e in members),
        platforms=sorted({e.source_platform.value for e in members}),
        identifiers=merged,
        match_keys=match_keys,
    )


def resolve_entities(
    entities: list[CanonicalEntity],
    merge_keys: Iterable[str] = DEFAULT_MERGE_KEYS,
    anchor_priority: tuple[PlatformType, ...] = DEFAULT_ANCHOR_PRIORITY,
) -> list[ResolvedEntity]:
    """Collapse provisional entities that share a normalized merge key.

    Pure and deterministic: returns resolved entities sorted by canonical_id.
    An entity with no merge keys (e.g. a NetBox device with null serial/MAC)
    forms its own singleton cluster rather than being dropped.
    """
    merge_keys = tuple(merge_keys)
    n = len(entities)
    parent = list(range(n))
    per_entity_keys: list[set[tuple[str, str]]] = []
    key_first_index: dict[tuple[str, str], int] = {}

    for idx, e in enumerate(entities):
        ks = identity_keys(e, merge_keys)
        per_entity_keys.append(ks)
        for k in ks:
            if k in key_first_index:
                _union(parent, idx, key_first_index[k])
            else:
                key_first_index[k] = idx

    clusters: dict[int, list[int]] = {}
    for idx in range(n):
        clusters.setdefault(_find(parent, idx), []).append(idx)

    resolved = [
        _build_resolved(
            [entities[i] for i in idxs],
            [per_entity_keys[i] for i in idxs],
            anchor_priority,
        )
        for idxs in clusters.values()
    ]
    resolved.sort(key=lambda r: r.canonical_id)
    return resolved


def cluster_for(resolved: list[ResolvedEntity], provisional_id: str) -> ResolvedEntity | None:
    """Find the resolved entity whose members include a given provisional id."""
    for r in resolved:
        if provisional_id in r.members:
            return r
    return None
