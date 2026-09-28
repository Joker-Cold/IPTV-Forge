# -*- coding: utf-8 -*-
"""
Rewrite ../HK-IPTV/Cold_Movie.json = the 12 picks + whatever of the
user's own entries is still alive and not a duplicate of one of them.

Keeps that file's existing conventions:
  - name suffix [优质] / [一般]
  - dead entries stay in the file, commented out with a reason
  - sequential numbering across active + commented

The previous version is backed up to data/Cold_Movie.json.bak-<date> first.
"""
import json
import os
import re
import shutil
import time
import warnings

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import decode_configs as D
import paths as P
import select_12 as S

warnings.simplefilter("ignore", InsecureRequestWarning)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 okhttp/3.15")

TARGET = P.COLD_MOVIE
DUP_LIMIT = 0.35


def parse_existing(path):
    """Return [(url, name, was_commented)] preserving file order."""
    out = []
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        commented = line.startswith("//")
        body = line.lstrip("/ ").strip()
        m = re.match(r'"(url|name)"\s*:\s*"(.*?)"\s*,?\s*$', body)
        if not m:
            continue
        if m.group(1) == "url":
            out.append([m.group(2), None, commented])
        elif out and out[-1][1] is None:
            out[-1][1] = m.group(2)
    return [(u, n, c) for u, n, c in out if u and n]


def probe(url):
    """(alive, note, decoded-signature-or-None)"""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25,
                         verify=False, allow_redirects=True)
    except Exception as e:
        return False, {"ReadTimeout": "读取超时", "ConnectTimeout": "连接超时",
                       "ConnectionError": "无法连接", "SSLError": "SSL 错误"
                       }.get(type(e).__name__, "连接失败"), None
    body = r.content or b""
    if r.status_code >= 400:
        return False, "HTTP %d" % r.status_code, None
    if len(body) < 2048:
        return False, "内容仅 %dB，非有效配置" % len(body), None
    low = body.lstrip()[:15].lower()
    if low.startswith((b"<!doctype html", b"<html")):
        return False, "返回 HTML 页面，非配置", None
    if body.lstrip()[:7].upper().startswith(b"#EXTM3U"):
        return False, "是直播 m3u，非影视仓配置", None

    sites = []
    try:
        cfg, _ = D.decode(body)
        sites = cfg.get("sites") or []
    except Exception:
        for text, _lbl in D.candidate_texts(body):
            got = D.regex_sites(text)
            if len(got) > len(sites):
                sites = got
    if not sites:
        return True, "可用(无法解析线路表)", None
    return True, "可用(%d 条线路)" % len(sites), S.sig({"sites": sites})


def main():
    picks = [json.loads(l) for l in open(P.SELECTED, encoding="utf-8") if l.strip()]
    idx = {r["url"]: r for r in json.load(open(P.SITES_INDEX, encoding="utf-8"))}
    pick_sigs = [(p, S.sig(idx[p["url"]])) for p in picks]
    pick_urls = {p["url"] for p in picks}

    existing = parse_existing(TARGET)
    print("existing entries: %d (%d active, %d commented)"
          % (len(existing), sum(1 for e in existing if not e[2]),
             sum(1 for e in existing if e[2])))

    keep, drop = [], []
    for url, name, was_commented in existing:
        label = re.sub(r"^[🚀\d\-]+", "", name)
        tag = "[优质]" if "[优质]" in name else "[一般]"
        base = re.sub(r"\[(优质|一般)\]", "", label).strip()
        if url in pick_urls:
            drop.append((url, base, tag, "已包含在精选中"))
            continue
        alive, note, sg = probe(url)
        if not alive:
            drop.append((url, base, tag, "❌失效(%s)" % note))
            print("  dead   %-14s %s" % (base[:12], note))
            continue
        dup = None
        if sg:
            for p, ps in pick_sigs:
                if S.sim(sg, ps) > DUP_LIMIT:
                    dup = p["name"]
                    break
        if dup:
            drop.append((url, base, tag, "与精选 %s 内容重复" % re.sub(r"^[🚀\d\-]+", "", dup)))
            print("  dup    %-14s -> %s" % (base[:12], dup))
        else:
            keep.append((url, base, tag, note))
            print("  KEEP   %-14s %s" % (base[:12], note))

    # ---------- render, in the target file's own style ----------
    L = ["{", '    "urls": [']
    n = 0
    rows = []
    for p in picks:
        rows.append(("active", p["url"],
                     re.sub(r"^[🚀\d\-]+", "", p["name"]), "[优质]", None))
    for url, base, tag, note in keep:
        rows.append(("active", url, base, tag, None))
    for url, base, tag, why in drop:
        rows.append(("comment", url, base, tag, why))

    n_active = sum(1 for r in rows if r[0] == "active")
    for i, (kind, url, base, tag, why) in enumerate(rows, 1):
        nm = "🚀%d-%s%s" % (i, base, tag)
        if kind == "active":
            n += 1
            last = (n == n_active)
            L.append("        {")
            L.append('            "url": "%s",' % url)
            L.append('            "name": "%s"' % nm)
            L.append("        }" + ("" if last else ","))
        else:
            L.append("        // %s —— 已注释" % why)
            L.append("        // {")
            L.append('        //     "url": "%s",' % url)
            L.append('        //     "name": "%s"' % nm)
            L.append("        // },")
    L += ["    ]", "}", ""]

    bak = os.path.join(P.DATA, "Cold_Movie.json.bak-" + time.strftime("%Y%m%d"))
    if not os.path.exists(bak):
        shutil.copy2(TARGET, bak)
        print("\nbacked up -> %s" % bak)
    open(TARGET, "w", encoding="utf-8").write("\n".join(L))
    print("wrote %s : %d active, %d commented"
          % (TARGET, n_active, len(rows) - n_active))


if __name__ == "__main__":
    main()
