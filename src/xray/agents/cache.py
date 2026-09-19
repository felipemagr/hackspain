"""One JSON file per key with a time to live.

Keeps demo lookups off the network and off the meter.
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class JsonCache:
    def __init__(self, directory: Path, ttl: timedelta):
        self.directory = directory
        self.ttl = ttl

    def path(self, key: str) -> Path:
        return self.directory / f"{slug(key)}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """The stored payload while it is younger than the TTL, else None."""
        path = self.path(key)
        if not path.exists():
            return None
        entry = json.loads(path.read_text())
        stored_at = datetime.fromisoformat(entry["stored_at"])
        if datetime.now(UTC) - stored_at > self.ttl:
            logger.info("Cache entry for %s expired", key)
            return None
        return entry["payload"]

    def put(self, key: str, payload: dict[str, Any]) -> Path:
        """Store the payload. A read-only folder (the deployed image) only costs the caching."""
        path = self.path(key)
        entry = {"key": key, "stored_at": datetime.now(UTC).isoformat(), "payload": payload}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, indent=2, ensure_ascii=False))
        except OSError as e:
            logger.warning("Could not cache %s: %s", key, e)
        return path
