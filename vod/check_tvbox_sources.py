# -*- coding: utf-8 -*-
"""
Check TVBox subscription sources for liveness.

Usage:
    python check_tvbox_sources.py <sources.json> [--proxy http://127.0.0.1:6738]

Verdict per source:
    OK    - reachable and returns TVBox-config-like content (json with
            sites/lives/spider/... or base64/encoded config, or substantial body)
    WARN  - reachable (HTTP 200) but body is empty / tiny / looks like an
            error or login page -> probably not a usable config
    DEAD  - unreachable: connection error, timeout, DNS failure, or HTTP >= 400
"""
import base64
import concurrent.futures
import json
import re
import sys
import warnings

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

warnings.simplefilter("ignore", InsecureRequestWarning)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 okhttp/3.15")
TIMEOUT = 15
CONFIG_KEYS = ("sites", "lives", "spider", "urls", "wallpaper", "parses", "doh")


def looks_like_config(text):
    """Return (is_config, detail). Tries plain json, then base64-decoded json."""
    t = text.strip()
    # strip // comments and trailing commas that TVBox tolerates
    cleaned = re.sub(r"^\s*//.*$", "", t, flags=re.M)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    for candidate in (t, cleaned):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and any(k in obj for k in CONFIG_KEYS):
                n = len(obj.get("sites", []) or [])
                return True, "json config, %d sites" % n
        except Exception:
            pass
    # maybe the whole body is base64-encoded config
    b = re.sub(r"\s+", "", t)
    if len(b) > 40 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", b):
        try:
            dec = base64.b64decode(b + "=" * (-len(b) % 4), validate=False)
            txt = dec.decode("utf-8", "ignore")
            if any('"%s"' % k in txt for k in CONFIG_KEYS):
                return True, "base64-encoded config"
        except Exception:
            pass
    return False, ""


def check(entry, proxies):
    url = entry["url"]
    name = entry["name"]
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT,
                         allow_redirects=True, verify=False, proxies=proxies)
    except requests.exceptions.SSLError as e:
        return dict(name=name, url=url, verdict="DEAD", info="SSL error", ms=0)
    except requests.exceptions.ConnectTimeout:
        return dict(name=name, url=url, verdict="DEAD", info="connect timeout", ms=0)
    except requests.exceptions.ReadTimeout:
        return dict(name=name, url=url, verdict="DEAD", info="read timeout", ms=0)
    except requests.exceptions.ConnectionError as e:
        msg = str(e).split("\n")[0][:60]
        return dict(name=name, url=url, verdict="DEAD", info="conn error: " + msg, ms=0)
    except Exception as e:
        return dict(name=name, url=url, verdict="DEAD", info=type(e).__name__ + ": " + str(e)[:50], ms=0)

    ms = int(r.elapsed.total_seconds() * 1000)
    body = r.content or b""
    size = len(body)
    ct = r.headers.get("content-type", "?").split(";")[0]

    if r.status_code >= 400:
        return dict(name=name, url=url, verdict="DEAD",
                    info="HTTP %d, %dB" % (r.status_code, size), ms=ms)

    text = body.decode("utf-8", "ignore")
    is_cfg, detail = looks_like_config(text)
    low = text.lstrip().lower()
    is_html = low.startswith("<!doctype html") or low.startswith("<html")

    if is_cfg:
        v, info = "OK", detail
    elif size < 50:
        v, info = "WARN", "tiny body %dB" % size
    elif is_html:
        v, info = "WARN", "HTML page (%dB, likely not config)" % size
    else:
        # 200 with substantial non-html body: usable content, config markers absent
        v, info = "OK", "%dB %s (no json markers, but has content)" % (size, ct)
    return dict(name=name, url=url, verdict=v, info="HTTP %d, %s" % (r.status_code, info), ms=ms)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    path = sys.argv[1]
    proxies = None
    if "--proxy" in sys.argv:
        p = sys.argv[sys.argv.index("--proxy") + 1]
        proxies = {"http": p, "https": p}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data["urls"]

    results = [None] * len(entries)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(check, e, proxies): i for i, e in enumerate(entries)}
        for fut in concurrent.futures.as_completed(futs):
            results[futs[fut]] = fut.result()

    order = {"OK": 0, "WARN": 1, "DEAD": 2}
    icon = {"OK": "[OK]  ", "WARN": "[WARN]", "DEAD": "[DEAD]"}
    print("\n===== TVBox Source Check =====")
    for r in results:
        print("%s %-22s %5sms  %s" % (icon[r["verdict"]], r["name"], r["ms"], r["info"]))
        print("        %s" % r["url"])

    n_ok = sum(1 for r in results if r["verdict"] == "OK")
    n_warn = sum(1 for r in results if r["verdict"] == "WARN")
    n_dead = sum(1 for r in results if r["verdict"] == "DEAD")
    print("\nSummary: %d OK, %d WARN, %d DEAD (of %d)" % (n_ok, n_warn, n_dead, len(results)))


if __name__ == "__main__":
    main()
