"""Runtime discovery of dataset locations from official landing pages and catalogues.

Nothing here hardcodes a file name or dataset ID. Each helper logs what it found
and raises SourceFormatChanged with a clear message when the page no longer
looks as expected.
"""

import html as htmllib
import json
import logging
import re
from urllib.parse import urljoin

from . import SourceFormatChanged

log = logging.getLogger(__name__)

GOVUK_CONTENT_API = "https://www.gov.uk/api/content"
ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"
ARCGIS_ITEM = "https://www.arcgis.com/sharing/rest/content/items"
NOMIS_API = "https://www.nomisweb.co.uk/api/v01"


def html_links(html: str, base: str) -> list[tuple[str, str]]:
    """Return (absolute_url, link_text) for every anchor in html."""
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        out.append((urljoin(base, htmllib.unescape(m.group(1))), re.sub(r"\s+", " ", htmllib.unescape(text)).strip()))
    return out


def html_links_with_heading(html: str, base: str) -> list[tuple[str, str, str]]:
    """Like html_links, plus the text of the nearest heading above each link."""
    headings = [(m.start(), re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip())
                for m in re.finditer(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html, re.S | re.I)]
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        above = [h for pos, h in headings if pos < m.start()]
        text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((urljoin(base, htmllib.unescape(m.group(1))), text, above[-1] if above else ""))
    return out


def govuk_content(fetcher, path: str, **kw) -> dict:
    path = path.replace("https://www.gov.uk", "").lstrip("/")
    return fetcher.get_json(f"{GOVUK_CONTENT_API}/{path}", **kw)


def govuk_links(content: dict) -> list[tuple[str, str]]:
    """All attachment and body links on a gov.uk content item, in page order."""
    details = content.get("details", {})
    links = [(a.get("url", ""), a.get("title", "")) for a in details.get("attachments", [])]
    body = details.get("body", "")
    if isinstance(body, list):
        body = " ".join(b.get("content", "") for b in body)
    links += html_links(body, "https://www.gov.uk")
    return [(urljoin("https://www.gov.uk", u), t) for u, t in links if u]


def first_match(links, pattern: str, what: str, page: str) -> str:
    for url, text in links:
        if re.search(pattern, url, re.I) or re.search(pattern, text, re.I):
            log.info("discovered %s: %s", what, url)
            return url
    raise SourceFormatChanged(
        f"Could not find {what} on {page} (looked for /{pattern}/ in {len(links)} links). "
        "The page layout may have changed; check it by hand."
    )


def arcgis_search(fetcher, query: str, num: int = 20) -> list[dict]:
    data = fetcher.get_json(ARCGIS_SEARCH, params={
        "q": query, "sortField": "modified", "sortOrder": "desc", "num": num, "f": "json"})
    return data.get("results", [])


def arcgis_item(fetcher, item_id: str) -> dict:
    return fetcher.get_json(f"{ARCGIS_ITEM}/{item_id}", params={"f": "json"})


def arcgis_item_data(fetcher, item_id: str, portal: str = "https://www.arcgis.com") -> dict:
    return fetcher.get_json(f"{portal}/sharing/rest/content/items/{item_id}/data", params={"f": "json"})


def arcgis_query_all(fetcher, layer_url: str, where: str, out_fields: str = "*",
                     geometry: bool = False, out_sr: int = 4326, fmt: str = "json",
                     page_size: int | None = None) -> list[dict]:
    """Page through an ArcGIS FeatureServer layer query and return all features."""
    meta = fetcher.get_json(layer_url, params={"f": "json"})
    max_count = page_size or meta.get("maxRecordCount") or 1000
    features, offset = [], 0
    while True:
        params = {
            "where": where, "outFields": out_fields, "returnGeometry": str(geometry).lower(),
            "f": fmt, "resultOffset": offset, "resultRecordCount": max_count,
        }
        if geometry:
            params["outSR"] = out_sr
        if meta.get("objectIdField"):
            params["orderByFields"] = meta["objectIdField"]
        data = fetcher.get_json(f"{layer_url}/query", params=params)
        if "error" in data:
            fetcher.invalidate("GET", f"{layer_url}/query", params)
            raise SourceFormatChanged(f"ArcGIS query error from {layer_url}: {data['error']} (params {params})")
        batch = data.get("features", [])
        features.extend(batch)
        if len(batch) < max_count and not data.get("exceededTransferLimit"):
            break
        offset += len(batch)
        if not batch:
            break
    return features


def webapp_layers_from_landing_page(fetcher, landing_page: str) -> tuple[str, list[dict]]:
    """Follow a council 'online maps' page to its ArcGIS web app, web map and layers.

    Returns (webmap_item_id, flat list of {title, url}).
    """
    page = fetcher.get_text(landing_page)
    m = re.search(r'https://([a-z0-9-]+\.maps\.arcgis\.com)/apps/[^"\']*?[?&]id=([0-9a-f]{32})', page)
    if not m:
        raise SourceFormatChanged(
            f"No ArcGIS web app link found on {landing_page}. Stop: catchment boundaries cannot be "
            "located programmatically, and they must not be guessed."
        )
    portal = f"https://{m.group(1)}"
    app = arcgis_item_data(fetcher, m.group(2), portal)
    map_id = (app.get("map") or {}).get("itemId") or (app.get("values") or {}).get("webmap")
    if not map_id:
        raise SourceFormatChanged(f"Web app {m.group(2)} has no web map reference; format changed.")
    webmap = arcgis_item_data(fetcher, map_id, portal)
    layers = []

    def walk(items):
        for item in items or []:
            if item.get("url"):
                layers.append({"title": item.get("title", ""), "url": item["url"]})
            walk(item.get("layers"))

    walk(webmap.get("operationalLayers"))
    log.info("web map %s has %d layers", map_id, len(layers))
    return map_id, layers


def nomis_dataset_id(fetcher, table_code: str) -> str:
    """Look up a Census 2021 table (e.g. TS021) in the Nomis catalogue."""
    data = fetcher.get_json(f"{NOMIS_API}/dataset/def.sdmx.json", params={"search": f"name-{table_code}*"})
    families = data.get("structure", {}).get("keyfamilies", {}).get("keyfamily", [])
    for fam in families:
        name = fam.get("name", {}).get("value", "")
        if name.startswith(f"{table_code} "):
            log.info("Nomis %s -> %s (%s)", table_code, fam["id"], name)
            return fam["id"]
    raise SourceFormatChanged(f"Nomis catalogue has no dataset named '{table_code} - ...'; found {len(families)} candidates.")


def nomis_codelist(fetcher, dataset_id: str, dimension: str) -> dict[str, str]:
    """Return {code: description} for a Nomis dataset dimension."""
    data = fetcher.get_json(f"{NOMIS_API}/dataset/{dataset_id}/{dimension}.def.sdmx.json")
    codes = data["structure"]["codelists"]["codelist"][0]["code"]
    return {str(c["value"]): c["description"]["value"] for c in codes}


def nomis_dimension_name(fetcher, dataset_id: str, prefix: str) -> str:
    data = fetcher.get_json(f"{NOMIS_API}/dataset/{dataset_id}.def.sdmx.json")
    dims = data["structure"]["keyfamilies"]["keyfamily"][0]["components"]["dimension"]
    for d in dims:
        if d["conceptref"].upper().startswith(prefix.upper()):
            return d["conceptref"]
    raise SourceFormatChanged(f"Nomis dataset {dataset_id} has no dimension starting {prefix}: {json.dumps(dims)[:300]}")
