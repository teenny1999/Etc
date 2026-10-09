"""M0: check that open data sources are reachable and usable.

Usage:
    python scripts/m0_check.py --plastics-repo PATH_TO_earthrise-media_plastics

Uses a real site from the earthrise Thailand confirmed-positives file as the
test location; no coordinates are invented.
"""
import argparse
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
import requests
from pystac_client import Client
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

warnings.filterwarnings("ignore")

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
S2_COLLECTION = "sentinel-2-c1-l2a"
# 12 bands used by the paper (B1-B9, B8A, B11, B12) mapped to Earth Search asset keys
BANDS = ["coastal", "blue", "green", "red", "rededge1", "rededge2", "rededge3",
         "nir", "nir08", "nir09", "swir16", "swir22"]
# SCL classes treated as clear: vegetation, bare soil, water, unclassified, snow
SCL_CLEAR = [4, 5, 6, 7, 11]
THAI_SITES = "data/sampling_locations/thailand_intersection_v0.0.11_v1.2_thresh_0.8_confirmed_positives.geojson"
NEIGHBOUR_SITES = {
    "Cambodia": "cambodia_intersection_v0.0.11_confirmed_positives.geojson",
    "Laos": "laos_intersection_v0.0.11_v1.2_thresh_0.4_confirmed_positives.geojson",
    "Myanmar": "myanmar_intersection_v0.0.11_v1.2_thresh_0.5_confirmed_positives.geojson",
    "Malaysia": "malaysia_intersection_v0.0.11_v1.2_thresh_0.8_confirmed_positives.geojson",
    "Vietnam": "vietnam_v0.0.7-v0.0.11_combined_positives.geojson",
}


def bbox_around(lon, lat, radius_km):
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * np.cos(np.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def read_window(href, bbox, out_shape=None, retries=4):
    for attempt in range(retries):
        try:
            with rasterio.open(href) as src:
                b = transform_bounds("EPSG:4326", src.crs, *bbox)
                win = from_bounds(*b, transform=src.transform)
                return src.read(1, window=win, boundless=True, fill_value=0, out_shape=out_shape)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def probe(url, **kw):
    try:
        r = requests.get(url, timeout=30, **kw)
        return f"HTTP {r.status_code}"
    except Exception as e:
        return f"FAIL {type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plastics-repo", required=True, type=Path)
    ap.add_argument("--start", default="2026-07-01")
    ap.add_argument("--end", default="2026-09-30")
    args = ap.parse_args()

    print("## Endpoints")
    print("Earth Search STAC:", probe(EARTH_SEARCH))
    print("Planetary Computer STAC:", probe(PC_STAC))
    print("Global Plastic Watch /countries/THA/sites (no key):",
          probe("https://api.globalplasticwatch.org/countries/THA/sites", params={"limit": 1}))
    print("Overpass:", probe("https://overpass-api.de/api/interpreter",
                             params={"data": "[out:json];node(13.75,100.5,13.751,100.501);out count;"}))

    print("\n## Open site labels (earthrise-media/plastics)")
    sites = json.loads((args.plastics_repo / THAI_SITES).read_text())["features"]
    print("Thailand confirmed positives:", len(sites))
    for country, f in NEIGHBOUR_SITES.items():
        n = len(json.loads((args.plastics_repo / "data/sampling_locations" / f).read_text())["features"])
        print(f"{country}: {n}")

    lon, lat = sites[5]["geometry"]["coordinates"]
    print(f"\n## Sentinel-2 test at site lat={lat:.5f} lon={lon:.5f}")
    cat = Client.open(EARTH_SEARCH)
    bbox = bbox_around(lon, lat, 5)
    items = list(cat.search(collections=[S2_COLLECTION], bbox=bbox,
                            datetime=f"{args.start}/{args.end}").items())
    print(f"{S2_COLLECTION}: {len(items)} scenes in {args.start}..{args.end}")
    best = min(items, key=lambda i: i.properties["eo:cloud_cover"])
    rb = best.assets["red"].extra_fields.get("raster:bands", [{}])[0]
    print("scale/offset:", rb.get("scale"), rb.get("offset"))

    for radius in (5, 10, 20):
        bb = bbox_around(lon, lat, radius)
        t = time.time()
        with ThreadPoolExecutor(4) as ex:
            arrs = list(ex.map(lambda k: read_window(best.assets[k].href, bb), BANDS + ["scl"]))
        print(f"radius {radius} km: 13 assets of one scene in {time.time() - t:.1f}s, red shape {arrs[3].shape}")

    t = time.time()
    epsg = best.properties.get("proj:epsg") or best.properties.get("proj:code")
    same_crs = [i for i in items if (i.properties.get("proj:epsg") or i.properties.get("proj:code")) == epsg]
    with ThreadPoolExecutor(4) as ex:
        scls = list(ex.map(lambda i: read_window(i.assets["scl"].href, bbox, out_shape=(500, 500)), same_crs))
    clear = np.sum([np.isin(a, SCL_CLEAR) for a in scls], axis=0)
    print(f"SCL over {len(same_crs)} scenes ({time.time() - t:.0f}s): "
          f"pixels with >=1 clear obs {100 * (clear >= 1).mean():.1f}%, "
          f">=3 clear obs {100 * (clear >= 3).mean():.1f}%, median {np.median(clear):.0f}")


if __name__ == "__main__":
    main()
