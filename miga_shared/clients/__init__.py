"""Reusable async HTTP client for all Cisco platform REST APIs."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx
from miga_shared.errors import PlatformAPIError, RateLimitError

logger = logging.getLogger("miga.cisco_api")
MAX_RETRIES = 3
BACKOFF = [1.0, 2.0, 4.0]


class CiscoAPIClient:
    """Async HTTP client with retry, rate-limit back-off, and auth injection."""

    def __init__(
        self,
        base_url: str,
        headers: Optional[dict[str, str]] = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        platform_name: str = "cisco",
    ):
        self.base_url = base_url.rstrip("/")
        self.platform_name = platform_name
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Content-Type": "application/json", **(headers or {})},
            verify=verify_ssl,
            timeout=timeout,
        )

    # -- Factories for each Cisco platform ------------------------------------

    @classmethod
    def for_catalyst_center(cls) -> CiscoAPIClient:
        return cls(
            base_url=os.getenv("CATALYST_CENTER_BASE_URL", ""),
            verify_ssl=os.getenv("CATALYST_CENTER_VERIFY_SSL", "true").lower() == "true",
            platform_name="catalyst_center",
        )

    @classmethod
    def for_meraki(cls) -> CiscoAPIClient:
        return cls(
            base_url=os.getenv("MERAKI_BASE_URL", "https://api.meraki.com/api/v1"),
            headers={"X-Cisco-Meraki-API-Key": os.getenv("MERAKI_API_KEY", "")},
            platform_name="meraki",
        )

    @classmethod
    def for_thousandeyes(cls) -> CiscoAPIClient:
        return cls(
            base_url=os.getenv("THOUSANDEYES_BASE_URL", "https://api.thousandeyes.com/v7"),
            headers={"Authorization": f"Bearer {os.getenv('THOUSANDEYES_API_TOKEN', '')}"},
            platform_name="thousandeyes",
        )

    @classmethod
    def for_webex(cls) -> CiscoAPIClient:
        return cls(
            base_url=os.getenv("WEBEX_API_BASE_URL", "https://webexapis.com/v1"),
            headers={"Authorization": f"Bearer {os.getenv('WEBEX_BOT_ACCESS_TOKEN', '')}"},
            platform_name="webex",
        )

    @classmethod
    def for_xdr(cls) -> CiscoAPIClient:
        return cls(
            base_url=os.getenv("XDR_BASE_URL", "https://api.xdr.security.cisco.com"),
            platform_name="xdr",
        )

    @classmethod
    def for_security_cloud_control(cls) -> CiscoAPIClient:
        return cls(
            base_url=os.getenv("SCC_BASE_URL", "https://api.security.cisco.com"),
            headers={"Authorization": f"Bearer {os.getenv('SCC_API_TOKEN', '')}"},
            platform_name="security_cloud_control",
        )

    # -- HTTP verbs -----------------------------------------------------------

    async def get(self, path: str, params: Optional[dict] = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json_data: Optional[dict] = None) -> Any:
        return await self._request("POST", path, json_data=json_data)

    async def put(self, path: str, json_data: Optional[dict] = None) -> Any:
        return await self._request("PUT", path, json_data=json_data)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)

    async def _request(self, method: str, path: str, **kw) -> Any:
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = await self._http.request(method, path, **kw)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", BACKOFF[attempt]))
                    logger.warning("%s rate-limited on %s %s, wait %.1fs", self.platform_name, method, path, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json() if resp.status_code != 204 else None
            except httpx.HTTPStatusError as e:
                last_err = e
                sc = e.response.status_code
                if sc in (401, 403):
                    raise PlatformAPIError(self.platform_name, "Auth failed", status_code=sc) from e
                if sc == 404:
                    raise PlatformAPIError(self.platform_name, f"Not found: {path}", status_code=404) from e
                if sc >= 500 and attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF[attempt])
                    continue
                raise PlatformAPIError(self.platform_name, e.response.text[:500], status_code=sc) from e
            except httpx.TimeoutException as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF[attempt])
                    continue
            except Exception as e:
                raise PlatformAPIError(self.platform_name, str(e)) from e

        raise PlatformAPIError(self.platform_name, f"Failed after {MAX_RETRIES} retries: {last_err}")

    async def close(self):
        await self._http.aclose()
