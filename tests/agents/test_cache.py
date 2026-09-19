import json
from datetime import timedelta

from xray.agents.cache import JsonCache


def test_round_trip_and_expiry(tmp_path):
    cache = JsonCache(tmp_path, ttl=timedelta(days=1))
    path = cache.put("Cabify España", {"hits": []})

    assert path.name == "cabify-espa-a.json"
    assert cache.get("Cabify España") == {"hits": []}

    entry = json.loads(path.read_text())
    entry["stored_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(entry))
    assert cache.get("Cabify España") is None
