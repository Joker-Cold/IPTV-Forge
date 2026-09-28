# -*- coding: utf-8 -*-
"""
Pick the 12 best mutually-non-redundant sources out of 多仓source.json.

Two ideas do the work:

1. "Duplicate" is decided on decoded CONTENT, not on the URL. Entries that
   serve the same site list through different hosts are one source, so all
   128 are clustered by site-set similarity and at most one member of any
   cluster can be selected.

2. Cluster size is itself the popularity signal. These 128 were harvested from
   many independent aggregators; a config that several of them chose to mirror
   is one the community trusts. That beats ranking on raw site count, which
   just favours whoever concatenated the most spiders.

Final score blends: mirror count, site count (log-scaled, so 1000 sites is not
10x better than 100), and reliability (direct origin, parses cleanly).

Writes output/selected_12.json (one JSON object per line)
"""
import json
import math
import re

import paths as P

DUP = 0.45            # cluster-merge: "this is the same source, republished"
EXCL = 0.35           # stricter bar for the final 12: meaningfully different
MIN_SITES = 25
N = 12

DECOR = re.compile(r"[^0-9a-z一-鿿]+")
PROXY = re.compile(r"gh-proxy|ghproxy|ghp\.ci|moeyy|gitmirror|githubraw|ghfast|"
                   r"gitdl|bgithub|cxkpro|3344550|con\.sh")
TESTY = re.compile(r"测试|test|demo|示例", re.I)


SPLIT = re.compile(r"[|｜/\\、,，·•\-—┃丨]+")
KEYPFX = re.compile(r"^(csp|drpy_js|drpy|drjs|lfjs|lf_js|hipy_js|hipy|py|js|t4|xb)_+",
                    re.I)


def norm(s):
    return DECOR.sub("", (s or "").lower())


def sig(rec):
    """Brand-independent fingerprint of what a config actually carries.

    Site labels are decorated per-repo ("📡豆瓣 | 雷蒙影视"), and a suffix that
    appears on nearly every entry is the publisher's own branding, not content.
    Left in, it makes a config look 0% similar to everyone else - i.e. it hides
    duplicates, which is the one error we cannot afford here. So any token
    occurring in over half of a config's own entries is dropped as branding.
    """
    sites = rec["sites"]
    parts_per_site, freq = [], {}
    for s in sites:
        toks = [p for p in (norm(x) for x in SPLIT.split(s.get("name") or ""))
                if len(p) >= 2]
        parts_per_site.append(toks)
        for t in set(toks):
            freq[t] = freq.get(t, 0) + 1

    n = len(sites)
    brand = {t for t, c in freq.items() if n >= 10 and c > n * 0.5}

    # one signature per site, not one per token: joining the surviving parts
    # keeps "豆瓣[js]" distinct from "豆瓣", whereas loose tokens would make
    # every config look similar through generic words like 豆瓣/直播/电影.
    names, keys = set(), set()
    for toks, s in zip(parts_per_site, sites):
        kept = [t for t in toks if t not in brand]
        if kept:
            names.add("".join(kept))
        k = norm(KEYPFX.sub("", s.get("key") or ""))
        if len(k) >= 2 and k not in brand:
            keys.add(k)
    return names, keys


def _pair(a, b):
    """max(jaccard, containment) - containment catches 'A is a superset of B',
    which plain jaccard misses when the two differ a lot in size."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return max(inter / float(len(a | b)), inter / float(min(len(a), len(b))))


def sim(a, b):
    """Compare on display names and on keys, take the stronger signal.

    Repos rename display labels but tend to keep keys, so either channel alone
    under-detects. Missing a duplicate is the costly error here, not flagging
    one extra."""
    return max(_pair(a[0], b[0]), _pair(a[1], b[1]))


def main():
    recs = json.load(open(P.SITES_INDEX, encoding="utf-8"))
    detail = {e["url"]: e for e in
              json.load(open(P.FINAL_DETAIL, encoding="utf-8"))}

    items = []
    for r in recs:
        s = sig(r)
        n_sites = len(r["sites"])
        if n_sites < MIN_SITES:
            continue
        d = detail.get(r["url"], {})
        names = [x.get("name", "") for x in r["sites"]]
        testy = sum(1 for n in names if TESTY.search(n)) / float(len(names) or 1)
        items.append(dict(url=r["url"], name=r["name"], sites=s, n=n_sites,
                          bytes=d.get("size", r.get("bytes", 0)),
                          wrapper=r["wrapper"], testy=testy,
                          mirrors=1 + len(d.get("dupes", []))))
    print("candidates with >=%d sites: %d" % (MIN_SITES, len(items)))

    # ---- single-linkage clustering on content similarity ----
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if sim(items[i]["sites"], items[j]["sites"]) > DUP:
                parent[find(i)] = find(j)

    clusters = {}
    for i, it in enumerate(items):
        clusters.setdefault(find(i), []).append(it)
    print("distinct sources after content clustering: %d" % len(clusters))

    # ---- score each cluster, choose its most reliable representative ----
    cands = []
    for members in clusters.values():
        # mirrors = same-content entries in this list + byte-identical dupes
        mirrors = sum(m["mirrors"] for m in members)
        best = max(members, key=lambda m: (
            0 if PROXY.search(m["url"]) else 1,      # direct origin first
            1 if m["wrapper"] == "plain" else 0,     # cleanly parseable
            m["n"]))
        cands.append(dict(rep=best, mirrors=mirrors, members=len(members),
                          n=max(m["n"] for m in members)))

    mx_mir = max(c["mirrors"] for c in cands)
    mx_site = max(math.log10(c["n"]) for c in cands)
    for c in cands:
        rep = c["rep"]
        pop = c["mirrors"] / float(mx_mir)
        size = math.log10(c["n"]) / mx_site
        rel = (0.0 if PROXY.search(rep["url"]) else 1.0) * 0.5 \
            + (0.5 if rep["wrapper"] == "plain" else 0.0)
        c["score"] = 0.45 * pop + 0.35 * size + 0.20 * rel - 1.5 * rep["testy"]
    cands.sort(key=lambda c: -c["score"])

    # ---- take the top 12, enforcing mutual non-duplication once more ----
    selected = []
    for c in cands:
        if len(selected) >= N:
            break
        if any(sim(c["rep"]["sites"], s["rep"]["sites"]) > EXCL for s in selected):
            continue
        selected.append(c)

    covered = set()
    print("\n%-3s %-22s %6s %7s %7s %s" % ("#", "name", "sites", "mirrors", "score", "url"))
    for i, c in enumerate(selected, 1):
        rep = c["rep"]
        c["new"] = len(rep["sites"][0] - covered)
        covered |= rep["sites"][0]
        print("%-3d %-22s %6d %7d %7.3f %s"
              % (i, rep["name"][:20], rep["n"], c["mirrors"], c["score"], rep["url"][:58]))

    print("\npairwise overlap (max of jaccard / containment):")
    worst = 0.0
    for i, a in enumerate(selected):
        row = []
        for j, b in enumerate(selected):
            if i == j:
                row.append("  - ")
                continue
            v = sim(a["rep"]["sites"], b["rep"]["sites"])
            worst = max(worst, v)
            row.append("%4.2f" % v)
        print("  %-16s %s" % (a["rep"]["name"][:14], " ".join(row)))
    print("\nhighest overlap between any two selected: %.2f" % worst)
    print("union coverage: %d distinct sites" % len(covered))

    with open(P.SELECTED, "w", encoding="utf-8") as f:
        for i, c in enumerate(selected, 1):
            rep = c["rep"]
            f.write(json.dumps({
                "rank": i,
                "name": "🚀%d-%s" % (i, re.sub(r"^[🚀\d\-]+", "", rep["name"])),
                "url": rep["url"],
                "sites": rep["n"],
                "new_sites": c["new"],
                # entries out of the 128 carrying substantially the same
                # content - mirrors, plus smaller configs this one subsumes
                "dup_entries": c["mirrors"],
                "format": rep["wrapper"],
                "bytes": rep["bytes"],
            }, ensure_ascii=False) + "\n")
    print("\nwrote %s (%d lines)" % (P.SELECTED, len(selected)))


if __name__ == "__main__":
    main()
