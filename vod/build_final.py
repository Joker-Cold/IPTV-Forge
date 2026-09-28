# -*- coding: utf-8 -*-
"""
Merge all probe reports, de-duplicate by response-body hash (the same config
is often served through several proxies), drop non-config entries, and emit:

    output/多仓source.json  curated, verified-live list (TVBox/影视仓 多仓 format)
    data/final_detail.json, data/aggregators.json, data/needs_manual_check.json
                            the split make_report.py turns into verify_report.md

Usage:  python build_final.py
"""
import concurrent.futures
import hashlib
import json
import os
import re
import warnings

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import paths as P

warnings.simplefilter("ignore", InsecureRequestWarning)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 okhttp/3.15")

# live-TV playlists / adult / non-config endpoints that slipped through
EXCLUDE = re.compile(r'''
    \.m3u8?($|\?)|iptv[46]?\.txt|/live/|zbds\.top|migu_video|epg|
    adult|成人|色情|18\+|av\d|porn|
    # 解析 (player/parse) endpoints harvested out of "parses" arrays - not 仓
    \?url=$|/jiexi|/vip\d*/\?url|player\.php|/parse
''', re.I | re.X)

# multi-repo (多仓) aggregators - valid, but nesting one inside a 多仓 file
# does not work in TVBox/影视仓, so they are listed separately instead.
AGGREGATOR = re.compile(r'tvboxmuti|/DC\.txt$|/dc/?$|/dc\.txt$|dc\.json$|duo\.json$|多仓', re.I)

MIN_BYTES = 2048          # a real single-repo config is comfortably bigger

REPORTS = [P.REPORT, P.REPORT2]
NAME_SRC = [P.CANDIDATES, P.HARVEST]


IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"PK\x03\x04", b"RIFF")
CFG_MARKER = re.compile(rb'"(sites|lives|spider|wallpaper|parses|urls)"')


def count_sites(raw):
    """Sites in a TVBox config. Tolerates BOM, // comments, trailing commas."""
    t = raw.decode("utf-8-sig", "ignore")
    t = re.sub(r'(?<![:"\w])//[^\n"]*$', "", t, flags=re.M)   # keep http:// intact
    t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    t = re.sub(r",\s*([}\]])", r"\1", t)
    try:
        return len(json.loads(t).get("sites", []) or [])
    except Exception:
        return 0


def body_hash(url):
    """Return (sha1-of-body, sites, bytes) or None if unusable as a config."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15,
                         verify=False, allow_redirects=True)
        if r.status_code >= 400:
            return None
        b = r.content or b""
        if len(b) < 50:
            return None
        # a real image/archive with no config markers is not a 仓
        # (note: plenty of genuine configs are *named* .png - only the bytes matter)
        if b.startswith(IMAGE_MAGIC) and not CFG_MARKER.search(b):
            return None
        # an m3u playlist is a 直播源, not a 影视仓 config - judge by the bytes,
        # since these are served from .json/.php paths with misleading names
        if b.lstrip()[:7].upper().startswith(b"#EXTM3U"):
            return None
        # a landing/error page is not a config. Encrypted configs served from
        # .html paths are fine - they are not actually HTML markup.
        if b.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")) \
                and not CFG_MARKER.search(b):
            return None
        return hashlib.sha1(b).hexdigest(), count_sites(b), len(b)
    except Exception:
        return None


def demojibake(s):
    """Repair UTF-8 text that was decoded as latin-1 somewhere upstream."""
    if not s or not re.search(r'[À-ÿ][-ÿ]', s):
        return s
    try:
        fixed = s.encode("latin-1").decode("utf-8")
        return fixed if re.search(r'[一-鿿]', fixed) else s
    except Exception:
        return s


# well-known sources, matched on a distinctive substring of the URL
KNOWN = [
    ("gaotianliuyun/gao/master/js", "高天流云js"),
    ("gaotianliuyun/gao/master/XYQ", "高天流云XYQ"),
    ("gaotianliuyun/gao", "高天流云"),
    ("yoursmile66/TVBox", "南风"), ("xyq254245", "香雅情"),
    ("maoystv/6/main/000", "猫云分享"), ("maoystv/6/main/001", "猫云分享者"),
    ("liucn.cc/box", "老刘备"), ("dxawi.github.io", "dxawi"),
    ("UndCover/PyramidStore", "金字塔UndCover"),
    ("guot55/yg/main/pg/jsm", "月光宝盒"), ("guot55/yg/main/pg/bh", "月光寳盒"),
    ("guot55/YGBH/main/pro", "宝盒4K"), ("guot55/YGBH/main/vip2", "宝盒VIP"),
    ("chitue/dongliTV", "东篱"), ("HeChengChaXiu", "荷城茶秀"),
    ("XiaoYiChaHang", "小忆茶行"), ("noimank", "健康家用"),
    ("xuanzhuapp", "玄珠"), ("qist/tvbox/master/jsm", "qist聚是猫"),
    ("qzz.io/jsm", "qist聚是猫"), ("qzz.io/xiaosa", "潇洒"),
    ("qist/tvbox/master/xiaosa", "潇洒"), ("qzz.io/fty", "饭太硬"),
    ("qist/tvbox/master/fty", "饭太硬"), ("yw88075", "yw影视"),
    ("duomv/dzhipy", "多蜜PY"), ("yydfys/yydf", "YYDF影视"),
    ("bitbucket.org/xduo", "小苹果"), ("kjsc0310.github.io", "小苹果2"),
    ("xzwei528/qixia", "七夏"), ("n3rddd/N3RD", "雷蒙"),
    ("jigedos/1024", "鸡哥"), ("hanhan8127", "胜寒"),
    ("lushunming", "撸顺明"), ("jundie.top", "俊佬"),
    ("xhztv.top/xhz", "小盒子"), ("xhztv.top/4k", "小盒子4K"),
    ("fmys.top", "蜂蜜影视"), ("ztha.top", "ZTHA"),
    ("iqinu.com", "奇努盒子"), ("jiekou.netlify.app", "接口SVIP"),
    ("蜗牛.top", "蜗牛"), ("yingm.cc", "影迷动漫"),
    ("hjfggzs.hjys", "汇聚影视"), ("xuexuguang/tvbox_spider", "学旭光"),
    ("bestpvp/tm", "时光机"), ("ymz1231/xymz", "夜猫子"),
    ("hackyjso/box", "橘子柚"), ("xnftv/xnf", "环宇轩"),
    ("wya6.cn", "无意线路"), ("szyyds", "闪电影视"),
    ("imwzh.com", "王志豪"), ("serv00.net", "张群"),
    ("3vcn.work", "我的家园"), ("web3v.work", "胡聪荣"),
    ("ufuzi.com", "短剧专线"), ("vicp.fun", "茄子库"),
    ("jyqhkd/kd", "凯迪"), ("pastebin.com/raw", "卧龙"),
    ("iptv365.org", "iptv365"), ("dokiss1", "doki"),
]


def name_from_url(url):
    """Best-effort readable name when no curated name is available."""
    for frag, nm in KNOWN:
        if frag.lower() in url.lower():
            return nm
    # strip any github-proxy prefix so we can read the real owner/repo
    u = re.sub(r'^https?://[^/]*?(?:gh-proxy|ghproxy|ghp\.ci|moeyy|gitmirror|'
               r'githubraw|ghfast|gitdl|bgithub|3344550|con\.sh|cxkpro)[^/]*/+'
               r'(?:https?:/+)?', 'https://', url)
    m = re.search(r'(?:githubusercontent\.com|github\.com|gitlab\.com|gitee\.com|'
                  r'jihulab\.com|bitbucket\.org|gitlink\.org\.cn)/+([^/]+)/+([^/]+)', u)
    if m:
        owner, repo = m.group(1), m.group(2)
        return owner if repo.lower() in ("tvbox", "box", "tv", "a", "raw") else "%s-%s" % (owner, repo)
    m = re.search(r'^https?://([^/:]+)', u)
    host = m.group(1) if m else ""
    tld = ("com", "net", "org", "cn", "co", "top", "xyz", "vip", "io", "cc",
           "site", "work", "fun", "live", "pro", "dev", "space", "eu", "app")
    sub = ("www", "api", "raw", "cdn", "tv", "m", "d", "z", "box", "play", "hb")
    parts = [p for p in host.split(".") if p not in tld and p not in sub]
    return parts[0] if parts else (host.split(".")[0] or "源")


def confirm(entries):
    """Final pass: re-probe each pick, 2 attempts each.

    Two attempts matter in both directions - a single parallel sweep throws
    spurious connection errors on healthy hosts, while a source that is merely
    slow-but-degraded fails consistently and should genuinely be dropped.
    """
    def alive(e):
        for _ in range(2):
            try:
                r = requests.get(e["url"], headers={"User-Agent": UA}, timeout=20,
                                 verify=False, allow_redirects=True)
                if r.status_code < 400 and len(r.content or b"") >= MIN_BYTES:
                    return True
            except Exception:
                pass
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        keep = list(ex.map(alive, entries))
    dropped = [e["url"] for e, k in zip(entries, keep) if not k]
    for u in dropped:
        print("  dropped (failed confirm x2): %s" % u)
    return [e for e, k in zip(entries, keep) if k]


def canonical_score(url):
    """Lower = preferred. Prefer direct origins over github proxy mirrors."""
    s = 0
    if re.search(r'gh-proxy|ghproxy|ghp\.ci|moeyy|gitmirror|githubraw|ghfast|'
                 r'g\.3344550|con\.sh|gitdl|cxkpro', url):
        s += 2
    if url.startswith("http://"):
        s += 1
    s += len(url) / 500.0
    return s


def main():
    names = {}
    for f in NAME_SRC:
        try:
            for u, n in json.load(open(f, encoding="utf-8")).items():
                n = (n or "").strip()
                if n and not names.get(u):
                    names[u] = n
        except Exception:
            pass
    # Hand-curated names from the ORIGINAL list win. Read the .bak, never the
    # live file - that is this script's own output, and re-reading it would
    # feed generated fallback names back in as if they were curated.
    orig = P.MULTI_BAK
    if not os.path.exists(orig):
        orig = P.MULTI
    for e in json.load(open(orig, encoding="utf-8"))["urls"]:
        n = re.sub(r'^[🚀\d\-\s]+', '', e["name"]).strip()
        if n:
            names[e["url"]] = n

    ok = {}
    for f in REPORTS:
        for r in json.load(open(f, encoding="utf-8")):
            if r["verdict"] == "OK" and not EXCLUDE.search(r["url"]):
                ok[r["url"]] = r
    # seed with the original list too, so a source the user already had is never
    # silently dropped just because no README happened to mention it. Anything
    # dead or non-config here still gets filtered out by the body_hash re-fetch.
    kept = 0
    for e in json.load(open(orig, encoding="utf-8"))["urls"]:
        if not EXCLUDE.search(e["url"]) and e["url"] not in ok:
            ok[e["url"]] = {"url": e["url"]}
            kept += 1
    print("OK candidates after exclusions: %d (+%d carried over from原清单)"
          % (len(ok), kept))

    hashes = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(body_hash, u): u for u in ok}
        for fut in concurrent.futures.as_completed(futs):
            res = fut.result()
            if res:
                hashes[futs[fut]] = res
    print("still-live on re-fetch:", len(hashes))

    # group by body hash, keep the most canonical url in each group
    groups = {}
    for u, (h, sites, size) in hashes.items():
        groups.setdefault(h, []).append((canonical_score(u), u, sites, size))
    final = []
    for h, members in groups.items():
        members.sort()
        _, u, sites, size = members[0]
        final.append(dict(url=u, sites=sites, size=size,
                          name=names.get(u, "").strip(),
                          dupes=[m[1] for m in members[1:]]))
    final.sort(key=lambda e: (-e["sites"], -e["size"]))

    # ---- name assignment ----
    used = set()
    for e in final:
        n = demojibake(e["name"] or "")
        n = re.sub(r'^(添加|还可以使用域名|加速|推荐|分享者?|接口|单仓|版本|更新时间\d*)$', '', n).strip()
        n = n or name_from_url(e["url"])
        base, i = n, 2
        while n in used:
            n, i = "%s%d" % (base, i), i + 1
        used.add(n)
        e["name"] = n

    # ---- split: verified single-repo configs vs. things needing eyeballs ----
    good = [e for e in final
            if not AGGREGATOR.search(e["url"]) and e["size"] >= MIN_BYTES]
    good = confirm(good)
    aggs = [e for e in final if AGGREGATOR.search(e["url"])]
    tiny = [e for e in final
            if not AGGREGATOR.search(e["url"]) and e["size"] < MIN_BYTES]
    print("unique configs after de-dup: %d  -> %d good, %d 多仓, %d tiny/unsure"
          % (len(final), len(good), len(aggs), len(tiny)))

    out = {"urls": [{"url": e["url"], "name": "🚀%d-%s" % (i, e["name"])}
                    for i, e in enumerate(good, 1)]}
    with open(P.MULTI, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)
    for fn, data in ((P.FINAL_DETAIL, good), (P.AGGREGATORS, aggs),
                     (P.NEEDS_MANUAL, tiny)):
        json.dump(data, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote %s with %d entries" % (P.MULTI, len(out["urls"])))


if __name__ == "__main__":
    main()
