# -*- coding: utf-8 -*-
"""
Verify candidate TVBox / 影视仓 config URLs and emit a JSON report.

Reuses looks_like_config() from check_tvbox_sources.py so the verdict
rules stay in one place.

Usage:
    python verify_candidates.py [candidates.json] [-o report.json] [--workers 24]

Defaults: sources/candidates.json -> data/report.json

candidates.json is {"<url>": "<name hint>", ...}
report.json is [{url, name, verdict, info, sites, ms}, ...]
"""
import concurrent.futures
import json
import sys
import warnings

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import paths as P
from check_tvbox_sources import looks_like_config, UA

warnings.simplefilter("ignore", InsecureRequestWarning)

TIMEOUT = 12


def probe(url, name):
    r = dict(url=url, name=name, verdict="DEAD", info="", sites=0, ms=0)
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT,
                            allow_redirects=True, verify=False)
    except Exception as e:
        r["info"] = type(e).__name__ + ": " + str(e).split("\n")[0][:60]
        return r

    r["ms"] = int(resp.elapsed.total_seconds() * 1000)
    body = resp.content or b""
    size = len(body)
    if resp.status_code >= 400:
        r["info"] = "HTTP %d, %dB" % (resp.status_code, size)
        return r

    text = body.decode("utf-8", "ignore")
    is_cfg, detail = looks_like_config(text)
    low = text.lstrip().lower()
    is_html = low.startswith("<!doctype html") or low.startswith("<html")

    if is_cfg:
        r["verdict"], r["info"] = "OK", detail
        # pull the real site count out of the detail string when present
        try:
            obj = json.loads(text)
            r["sites"] = len(obj.get("sites", []) or [])
        except Exception:
            pass
    elif size < 50:
        r["verdict"], r["info"] = "WARN", "tiny body %dB" % size
    elif is_html:
        r["verdict"], r["info"] = "WARN", "HTML page %dB" % size
    else:
        r["verdict"] = "OK"
        r["info"] = "%dB %s (no json markers, has content)" % (
            size, resp.headers.get("content-type", "?").split(";")[0])
    return r


def main():
    src = P.CANDIDATES
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        src = sys.argv[1]
    out = P.REPORT
    if "-o" in sys.argv:
        out = sys.argv[sys.argv.index("-o") + 1]
    workers = 24
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers") + 1])

    with open(src, "r", encoding="utf-8") as f:
        cands = json.load(f)
    items = list(cands.items())

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(probe, u, n) for u, n in items]
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            results.append(fut.result())
            if i % 25 == 0:
                sys.stderr.write("  probed %d/%d\n" % (i, len(items)))

    rank = {"OK": 0, "WARN": 1, "DEAD": 2}
    results.sort(key=lambda r: (rank[r["verdict"]], -r["sites"], r["ms"]))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    n = {k: sum(1 for r in results if r["verdict"] == k) for k in rank}
    print("OK=%d WARN=%d DEAD=%d  (of %d) -> %s"
          % (n["OK"], n["WARN"], n["DEAD"], len(results), out))


if __name__ == "__main__":
    main()
