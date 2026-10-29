"""World countries dataset — ISO 3166-1, UN M49 regions, centroids.

Source files: ISO-3166-Countries-with-Regional-Codes (lukes) and
world-countries-centroids (gavinr), merged into data/countries.json.
"""

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "countries.json"


@lru_cache(maxsize=1)
def all_countries() -> list[dict]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def by_code() -> dict[str, dict]:
    return {c["code"]: c for c in all_countries()}


def country(code: str | None) -> dict | None:
    if not code:
        return None
    return by_code().get(code.upper())


def region_of(code: str | None) -> str:
    c = country(code)
    return (c or {}).get("region") or "—"


def centroid(code: str | None) -> tuple[float, float] | None:
    c = country(code)
    if c and c.get("lat") is not None:
        return (c["lat"], c["lon"])
    return None


def is_valid(code: str | None) -> bool:
    return country(code) is not None
