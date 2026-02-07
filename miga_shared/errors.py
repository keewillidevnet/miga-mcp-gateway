"""MIGA error hierarchy — consistent error handling across all services."""
from __future__ import annotations
from typing import Optional


class MIGAError(Exception):
    """Base exception for all MIGA errors."""
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(message)

    def to_tool_error(self) -> str:
        msg = f"Error: {self.message}"
        if self.details:
            msg += f"\nDetails: {self.details}"
        return msg


class PlatformAPIError(MIGAError):
    def __init__(self, platform: str, message: str, status_code: Optional[int] = None, **kw):
        self.platform = platform
        self.status_code = status_code
        full = f"[{platform}] HTTP {status_code}: {message}" if status_code else f"[{platform}] {message}"
        super().__init__(full, **kw)


class AuthenticationError(MIGAError):
    pass


class RateLimitError(PlatformAPIError):
    def __init__(self, platform: str, retry_after: float = 60.0):
        self.retry_after = retry_after
        super().__init__(platform, f"Rate limit exceeded. Retry after {retry_after:.0f}s.", status_code=429)


class DiscoveryError(MIGAError):
    pass


class ApprovalRequiredError(MIGAError):
    def __init__(self, tool_name: str, action_description: str):
        self.tool_name = tool_name
        super().__init__(f"Action '{tool_name}' requires approval: {action_description}")
