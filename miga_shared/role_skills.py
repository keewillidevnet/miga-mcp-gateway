"""Loader for the role -> OASF skills map used by directory-search discovery routing.

Best-effort: a missing or invalid file resolves to an empty map, so discovery routing
simply finds nothing and the gateway falls back to the static registry.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("miga.role_skills")

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROLE_SKILLS_PATH = _REPO_ROOT / "config" / "role-skills.yaml"
DEFAULT_SCHEMA_PATH = _REPO_ROOT / "config" / "role-skills.schema.json"


def load_role_skills(
    path: Path | str = DEFAULT_ROLE_SKILLS_PATH,
    *,
    schema_path: Path | str = DEFAULT_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, list[str]]:
    """Return {role: [skill, ...]}. Missing/invalid file returns {} (best-effort)."""
    path = Path(path)
    if not path.exists():
        logger.info("role-skills file not found at %s; discovery routing disabled", path)
        return {}
    try:
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("failed to read role-skills file %s: %r", path, exc)
        return {}

    if validate:
        try:
            import json

            import jsonschema

            with open(schema_path, encoding="utf-8") as fh:
                schema = json.load(fh)
            jsonschema.validate(data, schema)
        except ImportError:
            logger.warning("jsonschema not installed; skipping role-skills validation")
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning("role-skills file %s failed validation: %r", path, exc)
            return {}

    return {str(role): list(skills or []) for role, skills in data.items()}
