"""Entra ID JWT authentication and scoped token management."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from miga_shared.errors import AuthenticationError

logger = logging.getLogger("miga.auth")


@dataclass
class _TokenCache:
    _store: dict[str, tuple[str, float]] = field(default_factory=dict)

    def get(self, key: str) -> Optional[str]:
        if key in self._store:
            tok, exp = self._store[key]
            if time.time() < exp - 60:
                return tok
            del self._store[key]
        return None

    def put(self, key: str, token: str, expires_in: int) -> None:
        self._store[key] = (token, time.time() + expires_in)


_cache = _TokenCache()


class EntraIDAuth:
    """Microsoft Entra ID client-credentials flow."""

    def __init__(self, tenant_id: str = "", client_id: str = "", client_secret: str = ""):
        self.tenant_id = tenant_id or os.getenv("ENTRA_TENANT_ID", "")
        self.client_id = client_id or os.getenv("ENTRA_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("ENTRA_CLIENT_SECRET", "")
        self.authority = os.getenv(
            "ENTRA_AUTHORITY",
            f"https://login.microsoftonline.com/{self.tenant_id}",
        )
        self._http = httpx.AsyncClient(timeout=30.0)

    async def get_token(self, scope: str = "https://graph.microsoft.com/.default") -> str:
        cache_key = hashlib.sha256(f"{self.client_id}:{scope}".encode()).hexdigest()
        cached = _cache.get(cache_key)
        if cached:
            return cached

        try:
            resp = await self._http.post(
                f"{self.authority}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": scope,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            token = data["access_token"]
            _cache.put(cache_key, token, data.get("expires_in", 3600))
            return token
        except Exception as e:
            raise AuthenticationError(f"Entra ID auth failed: {e}") from e

    async def close(self):
        await self._http.aclose()


async def verify_jwt(token: str, audience: Optional[str] = None) -> dict[str, Any]:
    """Verify JWT against Entra ID JWKS. Returns decoded claims."""
    try:
        import jwt as pyjwt

        tenant_id = os.getenv("ENTRA_TENANT_ID", "")
        authority = os.getenv("ENTRA_AUTHORITY", f"https://login.microsoftonline.com/{tenant_id}")
        jwks_client = pyjwt.PyJWKClient(f"{authority}/discovery/v2.0/keys", cache_keys=True)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience or os.getenv("ENTRA_CLIENT_ID"),
            issuer=f"{authority}/v2.0",
        )
    except ImportError:
        # Dev fallback: decode without verification
        import base64 as b64
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("Invalid JWT format")
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(b64.urlsafe_b64decode(payload))
    except Exception as e:
        raise AuthenticationError(f"JWT verification failed: {e}") from e
