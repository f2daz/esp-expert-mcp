"""Live query of current framework/tool versions (GitHub releases, Espressif index).

Nothing is hard-coded: versions change monthly. Results are cached in-process for
one hour. GITHUB_TOKEN (optional) raises the rate limit.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

REPOS = {
    "esp-idf": "espressif/esp-idf",
    "arduino-esp32": "espressif/arduino-esp32",
    "esp8266-arduino": "esp8266/Arduino",
    "esphome": "esphome/esphome",
    "esptool": "espressif/esptool",
    "pioarduino-espressif32": "pioarduino/platform-espressif32",
    "platformio-espressif32": "platformio/platform-espressif32",
    "platformio-espressif8266": "platformio/platform-espressif8266",
    "lvgl": "lvgl/lvgl",
    "esp-adf": "espressif/esp-adf",
    "esp-matter": "espressif/esp-matter",
}
IDF_INDEX = "https://dl.espressif.com/dl/esp-idf/idf_versions.json"
TTL = 3600
_cache: dict[str, tuple[float, object]] = {}


def _get(url: str) -> object:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "esp-expert-mcp"})
    if (tok := os.environ.get("GITHUB_TOKEN")) and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    _cache[url] = (time.time(), data)
    return data


def _semver_key(tag: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", tag.split("-")[0])[:4]]
    return tuple(nums + [0] * (4 - len(nums)))


def releases(component: str, include_prerelease: bool = False, limit: int = 30) -> dict:
    repo = REPOS.get(component, component if "/" in component else None)
    if not repo:
        return {"error": f"Unknown component {component!r}. Known: {sorted(REPOS)} or 'owner/repo'."}
    try:
        data = _get(f"https://api.github.com/repos/{repo}/releases?per_page={limit}")
    except OSError as e:
        return {"error": f"GitHub unreachable: {e}"}
    rels = [
        {"tag": r["tag_name"], "published": r["published_at"][:10], "prerelease": r["prerelease"], "url": r["html_url"]}
        for r in data if not r.get("draft") and (include_prerelease or not r["prerelease"])
    ]
    by_version = sorted(rels, key=lambda r: _semver_key(r["tag"]), reverse=True)
    # Latest release per minor line (e.g. v6.1, v6.0.3, v5.5.5 …)
    lines: dict[str, dict] = {}
    for r in by_version:
        k = ".".join(str(x) for x in _semver_key(r["tag"])[:2])
        lines.setdefault(k, r)
    return {
        "repo": repo,
        "highest_version": by_version[0] if by_version else None,
        "latest_per_minor": list(lines.values()),
        "most_recently_published": max(rels, key=lambda r: r["published"]) if rels else None,
        "note": "‘most_recently_published’ may be a bugfix release of an old branch – for new projects use ‘highest_version’ "
                "or the framework's recommended version.",
        "source": f"https://github.com/{repo}/releases",
    }


def idf_targets(target: str | None = None) -> dict:
    try:
        data = _get(IDF_INDEX)
    except OSError as e:
        return {"error": f"Espressif index unreachable: {e}"}
    rows = []
    for v in data.get("VERSIONS", []):
        if "name" not in v or v.get("end_of_life"):
            continue
        targets = sorted(set(v.get("supported_targets", [])))
        if target and target.lower() not in targets:
            continue
        rows.append({"version": v["name"], "old": v.get("old", False), "pre_release": v.get("pre_release", False),
                     "supported_targets": targets})
    return {"source": IDF_INDEX, "target_filter": target, "versions": rows[:40]}


def overview() -> dict:
    out = {}
    for comp in ("esp-idf", "arduino-esp32", "esp8266-arduino", "esphome", "esptool", "pioarduino-espressif32"):
        r = releases(comp)
        out[comp] = r.get("highest_version") or r.get("error")
        if comp == "esp-idf" and "latest_per_minor" in r:
            out["esp-idf-lines"] = [x["tag"] for x in r["latest_per_minor"][:6]]
    out["note"] = ("The ESP-IDF version underlying the Arduino core is listed in the arduino-esp32 release notes. "
                   "PlatformIO: Arduino core 3.x is provided via the community platform pioarduino – "
                   "check its docs for the current status before use.")
    return out
