# -*- coding: utf-8 -*-
"""
Every file the vod pipeline reads or writes, anchored to this directory so the
scripts work from any cwd.

    sources/  hand-collected input      (candidates / harvest / 接口.txt)
    data/     intermediate results      (probe reports, site index, http cache)
    output/   what the pipeline produces (多仓source.json, selected_12, report)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, "sources")
DATA = os.path.join(HERE, "data")
OUTPUT = os.path.join(HERE, "output")

# sources/
CANDIDATES = os.path.join(SOURCES, "candidates.json")
HARVEST = os.path.join(SOURCES, "harvest.json")

# data/
REPORT = os.path.join(DATA, "report.json")
REPORT2 = os.path.join(DATA, "report2.json")
FINAL_DETAIL = os.path.join(DATA, "final_detail.json")
AGGREGATORS = os.path.join(DATA, "aggregators.json")
NEEDS_MANUAL = os.path.join(DATA, "needs_manual_check.json")
SITES_INDEX = os.path.join(DATA, "sites_index.json")
CACHE = os.path.join(DATA, "cache")

# output/
MULTI = os.path.join(OUTPUT, "多仓source.json")
MULTI_BAK = MULTI + ".bak"      # the hand-curated original list, if kept
SELECTED = os.path.join(OUTPUT, "selected_12.json")   # one JSON object per line
VERIFY_REPORT = os.path.join(OUTPUT, "verify_report.md")

# publish target: the HK-IPTV repo sitting next to this project - or, in a
# checkout without one, output/ like everything else
PUBLISH = os.path.normpath(os.path.join(HERE, "..", "..", "HK-IPTV"))
COLD_MOVIE = os.path.join(PUBLISH if os.path.isdir(PUBLISH) else OUTPUT, "Cold_Movie.json")
