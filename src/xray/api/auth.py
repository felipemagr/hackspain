"""The shared key in front of the API: one header, checked when a key is configured."""

import secrets

from fastapi import Header, HTTPException, status

from xray.settings import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject a call without the key. With no key configured, as in local work, all pass."""
    expected = get_settings().api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or wrong API key"
        )
