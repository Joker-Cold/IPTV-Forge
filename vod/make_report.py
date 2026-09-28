# -*- coding: utf-8 -*-
"""Generate output/verify_report.md from the probe reports + build_final output."""
import json
import re

import paths as P
from build_final import demojibake

EXCLUDE = re.compile(r'\.m3u8?($|\?)|iptv[46]?\.txt|zbds\.top|migu_video|epg|'
                     r'adult|成人|色情|porn|\?url=$|/jiexi|/vip\d*/\?url|/parse',
                     re.I)


def load(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d if d is not None else []


good = load(P.FINAL_DETAIL)
aggs = load(P.AGGREGATORS)
tiny = load(P.NEEDS_MANUAL)
old = load(P.MULTI_BAK, {"urls": []})["urls"]

warns = []
for f in (P.REPORT, P.REPORT2):
    for r in load(f):
        if r["verdict"] == "WARN" and not EXCLUDE.search(r["url"]):
            warns.append(r)
seen, uw = set(), []
for r in sorted(warns, key=lambda r: r["url"]):
    if r["url"] not in seen:
        seen.add(r["url"])
        uw.append(r)

L = []
A = L.append
A("# 影视仓 / TVBox 多仓源 采集与验证报告\n")
A("原始清单 %d 条，其中 12 条已失效。本次从 GitHub / GitLab / 各多仓聚合站"
  "重新采集并逐条验证，产出 **%d 条实测可用**的单仓接口。\n" % (len(old), len(good)))
A("- 采集来源：wuxierj/TVBox、Zhou-Li-Bin/Tvbox-QingNing、youhunwl/TVAPP、"
  "Newtxin/TVBoxSource、qist/tvbox、noimank/tvbox 等仓库 README，"
  "以及小盒子/游魂/拾光等多仓聚合站内部条目")
A("- 验证方式：实际 HTTP GET（okhttp UA）→ 判定是否为 TVBox 配置"
  "（明文 JSON / base64 / `2423` 十六进制加密 / `**` 分隔加密均视为有效）")
A("- 去重方式：按响应正文 SHA1 去重，同一份配置的多个代理镜像只保留一个"
  "（优先直连源、优先 https）")
A("- 已剔除：直播 m3u、解析(`?url=`)接口、真实图片文件（非伪装配置）\n")

A("\n## 一、已写入 `多仓source.json`（%d 条，实测可用）\n" % len(good))
A("| # | 名称 | 站点数 | 大小 | 地址 |")
A("|---|------|-------|------|------|")
for i, e in enumerate(good, 1):
    A("| %d | %s | %s | %dKB | `%s` |"
      % (i, e["name"], e["sites"] or "加密", e["size"] // 1024, e["url"]))

A("\n\n## 二、多仓聚合入口（%d 条，单独列出）\n" % len(aggs))
A("这些本身就是「多仓」清单，**不要**再填进 `多仓source.json`（不支持嵌套）；"
  "可直接作为影视仓的多仓地址单独使用，或用来定期采集新单仓。\n")
A("| 名称 | 地址 |")
A("|------|------|")
for e in aggs:
    A("| %s | `%s` |" % (e["name"], e["url"]))

A("\n\n## 三、待人工验证（%d 条）\n" % (len(uw) + len(tiny)))
A("以下地址能连通，但返回的是 HTML 页面或内容过短，脚本无法确认是不是配置。"
  "多为「需特定客户端 UA / 需在 App 内打开 / 落地页跳转」的接口，"
  "建议在影视仓里逐个手动试。\n")
A("| 名称 | 地址 | 探测结果 |")
A("|------|------|---------|")
for e in tiny:
    A("| %s | `%s` | 内容仅 %dB |" % (e["name"], e["url"], e["size"]))
for r in uw:
    A("| %s | `%s` | %s |" % (demojibake(r["name"]) or "-", r["url"], r["info"]))

A("\n\n## 复现方式\n")
A("```bash")
A("cd vod")
A("python verify_candidates.py   # 探测 sources/candidates.json -> data/report.json")
A("python build_final.py         # 去重并生成 output/多仓source.json")
A("python make_report.py         # 生成本报告")
A("```")
A("\n原始清单备份为 `output/多仓source.json.bak`（如有）。"
  "`build_final.py` 只从 `.bak` 读取人工命名，可重复执行。\n")
A("> 接口均为网络公开收集，随时可能失效或跑路；请勿相信其中任何付费/广告信息。\n")

open(P.VERIFY_REPORT, "w", encoding="utf-8").write("\n".join(L))
print("verify_report.md: %d good, %d aggregators, %d manual"
      % (len(good), len(aggs), len(uw) + len(tiny)))
