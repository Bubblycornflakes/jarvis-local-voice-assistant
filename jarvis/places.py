"""Getting around London: journey times from home and nearby places.
Uses free public services: postcodes.io, OpenStreetMap (Nominatim, OSRM, Overpass) and TfL."""
import functools
import math

import httpx

from . import config

UA = {"User-Agent": "JARVIS-personal-assistant/1.0"}


@functools.cache
def home() -> tuple[float, float]:
    r = httpx.get(f"https://api.postcodes.io/postcodes/{config.HOME_POSTCODE}", timeout=10).json()
    return r["result"]["latitude"], r["result"]["longitude"]


def _station(place: str) -> tuple[float, float, str] | None:
    """Airports and stations: use the actual station, not the middle of the runway."""
    r = httpx.get(f"https://api.tfl.gov.uk/StopPoint/Search/{place}",
                  params={"modes": "tube,elizabeth-line,national-rail,dlr,overground"}, timeout=10).json()
    words = {w for w in place.lower().split() if w not in ("airport", "station", "london", "the")}
    for m in r.get("matches", []):
        if words & set(m["name"].lower().split()):
            return m["lat"], m["lon"], m["name"]
    return None


def geocode(place: str) -> tuple[float, float, str] | None:
    """Find a place, preferring results near home (it's London, not London, Ontario)."""
    try:
        if found := _station(place):
            return found
    except Exception:  # noqa: BLE001
        pass
    lat, lon = home()
    params = {"q": place, "format": "json", "limit": 1, "countrycodes": "gb",
              "viewbox": f"{lon - 1.5},{lat + 1},{lon + 1.5},{lat - 1}"}
    r = httpx.get("https://nominatim.openstreetmap.org/search", params=params, headers=UA, timeout=10).json()
    if not r:
        r = httpx.get("https://nominatim.openstreetmap.org/search", params={"q": place, "format": "json", "limit": 1},
                      headers=UA, timeout=10).json()
    return (float(r[0]["lat"]), float(r[0]["lon"]), r[0]["display_name"].split(",")[0]) if r else None


def _mins(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60} hour{'s' if m // 60 > 1 else ''} {m % 60} minutes" if m >= 60 else f"{m} minutes"


def journey(place: str) -> str:
    dest = geocode(place)
    if not dest:
        return f"Couldn't find {place} on the map."
    lat, lon, name = dest
    hlat, hlon = home()
    out = [f"From home ({config.HOME_POSTCODE}) to {name}:"]
    try:  # driving, without live traffic
        r = httpx.get(f"https://router.project-osrm.org/route/v1/driving/{hlon},{hlat};{lon},{lat}",
                      params={"overview": "false"}, timeout=15).json()
        route = r["routes"][0]
        out.append(f"by car about {_mins(route['duration'])} for {route['distance'] / 1609:.0f} miles "
                   "(without traffic, so allow extra at rush hour)")
    except Exception:  # noqa: BLE001
        out.append("driving time unavailable")
    try:  # public transport via TfL
        r = httpx.get(f"https://api.tfl.gov.uk/Journey/JourneyResults/{hlat},{hlon}/to/{lat},{lon}", timeout=20).json()
        j = min(r["journeys"], key=lambda j: j["duration"])
        legs = [leg["instruction"]["summary"] for leg in j["legs"] if leg["mode"]["name"] != "walking"]
        out.append(f"by public transport about {_mins(j['duration'] * 60)}" + (f": {'; then '.join(legs)}" if legs else ""))
    except Exception:  # noqa: BLE001
        out.append("public transport times unavailable (TfL covers London and nearby)")
    return "; ".join(out[:1]) + " " + "; ".join(out[1:]) + "."


def nearby(kind: str, halal: bool = False, radius_m: int = 2000) -> str:
    lat, lon = home()
    amenity = {"restaurant": "restaurant|fast_food|cafe", "cafe": "cafe", "takeaway": "fast_food"}.get(kind, kind)
    diet = '["diet:halal"~"yes|only"]' if halal else ""
    q = f'[out:json][timeout:20];nwr["amenity"~"{amenity}"]{diet}(around:{radius_m},{lat},{lon});out center 40;'
    els = None
    for server in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                   "https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
        try:
            els = httpx.post(server, data={"data": q}, headers=UA, timeout=25).json()["elements"]
            break
        except Exception:  # noqa: BLE001  busy server, try the next
            continue
    if els is None:
        return ""
    found = []
    for e in els:
        t = e.get("tags", {})
        if not t.get("name"):
            continue
        c = e.get("center", e)
        dist = math.dist((lat * 111, lon * 69), (c["lat"] * 111, c["lon"] * 69))  # rough km
        found.append((dist, f"{t['name']} ({t.get('cuisine', t.get('amenity', '')).replace(';', ', ')}, {dist:.1f} km)"))
    found.sort()
    return "; ".join(f for _, f in found[:8])
