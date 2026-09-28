# -*- coding: utf-8 -*-
"""Re-probe the chosen 12 and show the publisher brand detected in each."""
import json
import warnings

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import paths as P
import select_12 as S

warnings.simplefilter("ignore", InsecureRequestWarning)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36 okhttp/3.15"

recs = {r["url"]: r for r in json.load(open(P.SITES_INDEX, encoding="utf-8"))}
sel = [json.loads(l) for l in open(P.SELECTED, encoding="utf-8") if l.strip()]

for s in sel:
    r = recs[s["url"]]
    # the brand token = what sig() strips as publisher decoration
    freq, n = {}, len(r["sites"])
    for site in r["sites"]:
        for p in S.SPLIT.split(site.get("name") or ""):
            p = S.norm(p)
            if len(p) >= 2:
                freq[p] = freq.get(p, 0) + 1
    brand = sorted([t for t, c in freq.items() if n >= 10 and c > n * 0.5],
                   key=lambda t: -freq[t])[:3]
    status = "?"
    try:
        resp = requests.get(s["url"], headers={"User-Agent": UA}, timeout=25,
                            verify=False, allow_redirects=True)
        status = "HTTP %d %dKB" % (resp.status_code, len(resp.content) // 1024)
    except Exception as e:
        status = "FAIL " + type(e).__name__
    print("%-2d %-20s %-16s brand=%-18s %s"
          % (s["rank"], s["name"][:18], status, ",".join(brand)[:16], s["url"][:52]))
