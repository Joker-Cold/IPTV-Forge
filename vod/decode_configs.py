# -*- coding: utf-8 -*-
"""
Fetch every entry of output/多仓source.json, decode it to plain JSON, and dump
the per-source site list to data/sites_index.json. Raw bodies are cached in
data/cache/ - delete it to force a re-fetch.

Handles the four wrappers seen in the wild:
  1. plain JSON (possibly BOM / // comments / trailing commas)
  2. whole body base64
  3. "<junk>**<base64>"        - the 欧歌 cache format
  4. "2423<keyhex>2324<cipherhex>" - TVBox AES-ECB, key right-padded to 16 with '0'
"""
import base64
import binascii
import concurrent.futures
import json
import os
import re
import warnings

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import paths as P

warnings.simplefilter("ignore", InsecureRequestWarning)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 okhttp/3.15")
CACHE = P.CACHE


def strip_comments(t):
    """Remove // and /* */ comments, but only outside of JSON strings.

    A regex cannot do this: comments here routinely contain quotes
    (`//"spider": "..."`, a commented-out line) and strings routinely
    contain `//` (every http:// URL).
    """
    out = []
    i, n = 0, len(t)
    instr = False
    while i < n:
        c = t[i]
        if instr:
            out.append(c)
            if c == "\\" and i + 1 < n:      # keep escape pairs intact
                out.append(t[i + 1])
                i += 2
                continue
            if c == '"':
                instr = False
            i += 1
            continue
        if c == '"':
            instr = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            if t[i + 1] == "/":
                while i < n and t[i] != "\n":
                    i += 1
                continue
            if t[i + 1] == "*":
                j = t.find("*/", i + 2)
                i = n if j < 0 else j + 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def loads_loose(text):
    """json.loads that tolerates what TVBox tolerates.

    These configs are hand-edited and routinely contain: BOM, // and /* */
    comments, trailing commas, raw newlines/tabs inside strings, and invalid
    escapes like \\d from regex literals. Java's lenient parser accepts all
    of it, so ours has to as well.
    """
    t = strip_comments(text.lstrip("﻿"))
    t = re.sub(r",\s*([}\]])", r"\1", t)
    try:
        # strict=False allows raw newlines/tabs inside strings
        return json.loads(t, strict=False)
    except json.JSONDecodeError:
        pass
    # Fallback: repair invalid escapes (e.g. \d from a regex literal). Match
    # valid escape pairs FIRST so a legitimate \\ is consumed as a unit - a
    # naive lookahead turns valid \\ + d into invalid \\ + \d.
    repaired = re.sub(r'\\(["\\/bfnrtu])|\\',
                      lambda m: m.group(0) if m.group(1) else "\\\\", t)
    return json.loads(repaired, strict=False)


def aes_decrypt(key_bytes, data):
    """TVBox '2423' configs: AES-128-CBC, key right-padded to 16 with '0',
    IV equal to that same key. (Verified against 蜗牛 / 奇努 / 月光宝盒.)"""
    key = key_bytes.ljust(16, b"0")[:16]
    dec = Cipher(algorithms.AES(key), modes.CBC(key)).decryptor()
    out = dec.update(data) + dec.finalize()
    if out and 1 <= out[-1] <= 16:          # strip PKCS#5/7 padding
        out = out[:-out[-1]]
    return out


# key/name pairs, in either order - used when the JSON will not parse at all
SITE_PAIRS = [
    re.compile(r'"key"\s*:\s*"([^"]{1,90})"\s*,\s*"name"\s*:\s*"([^"]{1,90})"'),
    re.compile(r'"name"\s*:\s*"([^"]{1,90})"\s*,\s*"key"\s*:\s*"([^"]{1,90})"'),
]


def regex_sites(text):
    """Best-effort site extraction from text that will not parse as JSON.

    Several configs are valid except at one spot, and the AES ones lose only
    their first 16 bytes to an IV variant - in both cases the site list itself
    is fully intact, which is all the overlap analysis needs.
    """
    out, seen = [], set()
    for i, rx in enumerate(SITE_PAIRS):
        for m in rx.finditer(text):
            key, name = (m.group(1), m.group(2)) if i == 0 else (m.group(2), m.group(1))
            if key not in seen:
                seen.add(key)
                out.append({"key": key, "name": name, "api": "", "ext": ""})
    return out


def decode(raw):
    """bytes -> (config dict, wrapper name). Raises on failure."""
    # 1. plain
    try:
        return loads_loose(raw.decode("utf-8", "ignore")), "plain"
    except Exception:
        pass

    txt = raw.decode("utf-8", "ignore").strip()

    # 4. TVBox hex-AES
    m = re.match(r"^\s*2423(.+?)2324(.+)$", txt, re.S)
    if m:
        try:
            key = binascii.unhexlify(m.group(1))
            ct = re.sub(r"\s+", "", m.group(2))
            # these files carry a trailing id/timestamp (13 ascii digits) after
            # the ciphertext; drop whatever does not fill a whole AES block
            tail = len(ct) % 32
            if tail:
                ct = ct[:-tail]
            out = aes_decrypt(key, binascii.unhexlify(ct))
            return loads_loose(out.decode("utf-8", "ignore")), "aes-2423"
        except Exception:
            pass

    # 3. prefix**base64
    if "**" in txt:
        try:
            b = re.sub(r"\s+", "", txt.split("**", 1)[1])
            dec = base64.b64decode(b + "=" * (-len(b) % 4))
            return loads_loose(dec.decode("utf-8", "ignore")), "b64-**"
        except Exception:
            pass

    # 2. whole-body base64
    b = re.sub(r"\s+", "", txt)
    if len(b) > 40 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", b):
        try:
            dec = base64.b64decode(b + "=" * (-len(b) % 4))
            return loads_loose(dec.decode("utf-8", "ignore")), "b64"
        except Exception:
            pass

    raise ValueError("undecodable")


def candidate_texts(raw):
    """Every plausible plaintext for a body, regardless of whether it parses."""
    txt = raw.decode("utf-8", "ignore").strip()
    yield txt, "plain"

    m = re.match(r"^\s*2423(.+?)2324(.+)$", txt, re.S)
    if m:
        ct = re.sub(r"\s+", "", m.group(2))
        tail = len(ct) % 32
        try:
            out = aes_decrypt(binascii.unhexlify(m.group(1)),
                              binascii.unhexlify(ct[:-tail] if tail else ct))
            yield out.decode("utf-8", "ignore"), "aes-2423"
        except Exception:
            pass

    for part in (txt.split("**", 1)[1] if "**" in txt else None, txt):
        if not part:
            continue
        b = re.sub(r"\s+", "", part)
        if len(b) > 40 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", b):
            try:
                yield (base64.b64decode(b + "=" * (-len(b) % 4))
                       .decode("utf-8", "ignore"), "b64")
            except Exception:
                pass


def fetch(entry):
    url, name = entry["url"], entry["name"]
    fn = os.path.join(CACHE, re.sub(r"\W+", "_", url)[:120] + ".bin")
    raw = None
    if os.path.exists(fn):
        raw = open(fn, "rb").read()
    else:
        for _ in range(2):
            try:
                r = requests.get(url, headers={"User-Agent": UA}, timeout=25,
                                 verify=False, allow_redirects=True)
                if r.status_code < 400 and r.content:
                    raw = r.content
                    open(fn, "wb").write(raw)
                    break
            except Exception:
                pass
    rec = dict(url=url, name=name, wrapper="FETCH-FAIL", sites=[], n=0,
               bytes=len(raw or b""))
    if not raw:
        return rec
    try:
        cfg, wrap = decode(raw)
        sites = cfg.get("sites") or []
    except Exception:
        # unwrap as far as we can, then scrape the site list out of the text
        best, wrap = [], "UNDECODABLE"
        for text, label in candidate_texts(raw):
            got = regex_sites(text)
            if len(got) > len(best):
                best, wrap = got, label + "+regex"
        if not best:
            rec["wrapper"] = "UNDECODABLE"
            return rec
        sites, cfg = best, {}
    rec["wrapper"] = wrap
    out = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        out.append({"key": str(s.get("key", "")), "name": str(s.get("name", "")),
                    "api": str(s.get("api", "")), "ext": json.dumps(
                        s.get("ext", ""), ensure_ascii=False)[:400]})
    rec["sites"] = out
    rec["n"] = len(out)
    return rec


def main():
    os.makedirs(CACHE, exist_ok=True)
    entries = json.load(open(P.MULTI, encoding="utf-8"))["urls"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        recs = list(ex.map(fetch, entries))
    json.dump(recs, open(P.SITES_INDEX, "w", encoding="utf-8"),
              ensure_ascii=False)
    from collections import Counter
    c = Counter(r["wrapper"] for r in recs)
    print("wrappers:", dict(c))
    print("total %d sources, %d parsed with sites, %d sites total"
          % (len(recs), sum(1 for r in recs if r["n"]),
             sum(r["n"] for r in recs)))
    bad = [r for r in recs if r["wrapper"] in ("UNDECODABLE", "FETCH-FAIL")]
    for r in bad:
        print("  %-12s %-22s %s" % (r["wrapper"], r["name"][:20], r["url"][:70]))


if __name__ == "__main__":
    main()
