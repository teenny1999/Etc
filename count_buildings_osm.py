#!/usr/bin/env python3
"""
Count buildings/roofs within a radius around a coordinate using the
OpenStreetMap Overpass API.

Usage:
    python count_buildings_osm.py <lat> <lon> [--radius METERS] [--endpoint URL]

Example:
    python count_buildings_osm.py 13.7563 100.5018 --radius 2000
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

DEFAULT_RADIUS_M = 2000
QUERY_TIMEOUT_S = 60  # server-side Overpass [timeout:] budget
HTTP_TIMEOUT_S = 120  # client-side socket timeout, must exceed QUERY_TIMEOUT_S
MAX_RETRIES = 3


def build_query(lat: float, lon: float, radius_m: int) -> str:
    return f"""
[out:json][timeout:{QUERY_TIMEOUT_S}];
(
  way["building"](around:{radius_m},{lat},{lon});
  relation["building"](around:{radius_m},{lat},{lon});
  node["building"](around:{radius_m},{lat},{lon});
);
out count;
""".strip()


def run_overpass_query(query: str, endpoints: list[str]) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")

    last_error: Exception | None = None
    for endpoint in endpoints:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                request = urllib.request.Request(
                    endpoint,
                    data=data,
                    headers={"User-Agent": "count-buildings-osm/1.0"},
                )
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_error = exc
                print(
                    f"[warn] {endpoint} attempt {attempt}/{MAX_RETRIES} failed: {exc}",
                    file=sys.stderr,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)
        print(f"[warn] giving up on {endpoint}, trying next mirror", file=sys.stderr)

    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")


def extract_total_count(result: dict) -> int:
    for element in result.get("elements", []):
        if element.get("type") == "count":
            tags = element.get("tags", {})
            total = tags.get("total")
            if total is not None:
                return int(total)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count OSM buildings/roofs within a radius of a coordinate."
    )
    parser.add_argument("lat", type=float, help="Latitude of the center point")
    parser.add_argument("lon", type=float, help="Longitude of the center point")
    parser.add_argument(
        "--radius",
        type=int,
        default=DEFAULT_RADIUS_M,
        help=f"Search radius in meters (default: {DEFAULT_RADIUS_M})",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="Overpass API endpoint(s) to try; can be given multiple times. "
        "Defaults to a built-in list of public mirrors.",
    )
    args = parser.parse_args()

    endpoints = args.endpoints or DEFAULT_ENDPOINTS

    query = build_query(args.lat, args.lon, args.radius)
    print(
        f"Querying Overpass API for buildings within {args.radius} m "
        f"of ({args.lat}, {args.lon})...",
        file=sys.stderr,
    )

    result = run_overpass_query(query, endpoints)
    total = extract_total_count(result)

    print(f"lat: {args.lat}")
    print(f"lon: {args.lon}")
    print(f"radius_m: {args.radius}")
    print(f"building_count: {total}")


if __name__ == "__main__":
    main()
