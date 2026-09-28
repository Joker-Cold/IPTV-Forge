# IPTV-Forge

直播（IPTV）+ 点播（TVBox / 影视仓）源的 **采集 → 测速 → 分组 → 发布** 流水线。

产物发布到与本仓库并排 clone 的 `HK-IPTV` 仓库：

| 产物 | 内容 | 由谁生成 |
|---|---|---|
| `HK-IPTV/COLD_OK.m3u8` | 测速后的直播源，港澳台优先，其余按大洲分组 | [update_live.bat](update_live.bat) |
| `HK-IPTV/Cold_Movie.json` | 影视仓多仓配置，12 个内容互不重复的精选仓 + 仍可用的自选仓 | [vod/update_cold_movie.py](vod/update_cold_movie.py) |

`HK-IPTV/COLD_OK.json` + `COLD_OK.jar`（单仓配置及其 spider）为手工维护，不由本仓库生成。

```
├── update_live.bat        一键更新直播
├── iptv_api/              直播抓取+测速引擎（iptv-api Docker 镜像）的配置
│   ├── docker-compose.yml
│   └── config/            订阅、频道模板、别名、测速参数、EPG
├── live/                  直播
│   ├── sources/           手工收集的本地直播源，挂载为容器的 config/local
│   ├── post_classify.py   按 香港/澳门/台湾/各大洲 重新分组
│   └── update_live.py     一键流程本体
└── vod/                   点播
    ├── sources/           候选接口
    ├── data/              中间结果（探测报告等）
    ├── output/            多仓source.json、selected_12.json、verify_report.md
    ├── paths.py           所有文件路径只在这里定义
    └── *.py               流水线脚本，见下文
```

依赖：Python 3.11 + `pip install requests cryptography`、Docker Desktop、宿主机 HTTP 代理（端口在 [user_config.ini](iptv_api/config/user_config.ini) 的 `http_proxy`）。

目录约定：本仓库和 `HK-IPTV` 放在同一个父目录下，脚本都用相对路径 `../HK-IPTV` 找它。

---

## 直播

```
iptv_api/config/subscribe.txt   在线订阅 ┐
live/sources/*                  本地源   ├─ iptv-api 容器 抓取+测速 ─→ iptv_api/output/cold_result.m3u
iptv_api/config/user_demo.txt   频道模板 ┘
    ─→ live/post_classify.py ─→ live/output/COLD_result.m3u ─→ ../HK-IPTV/COLD_OK.m3u8
```

**运行：双击 [update_live.bat](update_live.bat)**（约 15 分钟）。流程在 [live/update_live.py](live/update_live.py)：

1. 确认 Docker 在跑，没开就启动 Docker Desktop
2. 检查代理能不能连上，连不上只警告（订阅会抓取失败）
3. 重建 `iptv-api` 容器 —— `update_startup=True`，一启动就跑一次完整更新；等日志出现「更新完成」
4. 停掉容器（不然它会按 12 小时间隔自己再跑，那些结果并不会被发布）
5. [post_classify.py](live/post_classify.py) 分组，复制到 `../HK-IPTV/COLD_OK.m3u8`。以下情况拒绝发布：
   结果是跑到一半的「正在更新中」版本，或条目数比当前发布版少一半以上
6. 然后去 `HK-IPTV` commit + push

参数加在 bat 后面，例如 `update_live.bat --no-docker`：

| 参数 | 作用 |
|---|---|
| `--no-docker` | 不跑容器，直接处理上一次的结果 |
| `--no-publish` | 只生成 `live/output/COLD_result.m3u`，不复制到 HK-IPTV |
| `--keep-running` | 跑完不停容器 |
| `--force` | 跳过上面两条发布检查 |

**想改什么去哪改：**

| 想要 | 改这里 |
|---|---|
| 加/删在线订阅源 | [iptv_api/config/subscribe.txt](iptv_api/config/subscribe.txt) |
| 加本地源文件（m3u / txt） | 放进 [live/sources/](live/sources/) |
| 频道列表和分类 | [iptv_api/config/user_demo.txt](iptv_api/config/user_demo.txt) |
| 频道别名（繁简/英文/带后缀的各种写法） | [iptv_api/config/alias.txt](iptv_api/config/alias.txt) |
| 测速门槛、并发、代理、更新间隔 | [iptv_api/config/user_config.ini](iptv_api/config/user_config.ini) |
| EPG 节目单 | [iptv_api/config/epg.txt](iptv_api/config/epg.txt) |
| 最终结果的地区分组规则 | [live/post_classify.py](live/post_classify.py) |

**注意：**

- 容器跑的是 `guovern/iptv-api:latest` 镜像，本仓库只提供它的 `config/` 和 compose 文件。
  升级镜像：`docker compose -f iptv_api/docker-compose.yml pull`，下次运行自动用上。
- 测速必须直连：[docker-compose.yml](iptv_api/docker-compose.yml) 里故意不设 `HTTP_PROXY`（原因见其注释），
  代理只在 `user_config.ini` 里给订阅抓取用。
- `user_config.ini` 的 `open_auto_disable_source = False` 不要改回去：代理一挂它会把 `subscribe.txt` 全部注释掉。
- 用 `docker restart` / Docker Desktop 手动跑时，别在跑完前拿 `cold_result.m3u` 去发布 —— 中途里面是「🕘️正在更新中」的中间结果。
- 付费订阅的本地源不入库（见 [.gitignore](.gitignore)），clone 后自行放进 `live/sources/`。
- 镜像拉不下来：在 `%USERPROFILE%\.docker\daemon.json` 配国内镜像源，或者开代理。

---

## 点播（TVBox / 影视仓）

脚本在 [vod/](vod/) 里，按顺序跑；不依赖当前目录：

| # | 脚本 | 做什么 | 写出 |
|---|---|---|---|
| 0 | —— | 从 GitHub、GitLab、多仓聚合站收集候选 | `sources/candidates.json`、`sources/harvest.json` |
| 1 | [verify_candidates.py](vod/verify_candidates.py) `[文件] [-o 输出]` | 逐个请求，判断是不是 TVBox 配置（明文/base64/加密都算） | `data/report.json` |
| 2 | [build_final.py](vod/build_final.py) | 合并报告，按响应内容去重，剔除直播/解析/聚合入口 | `output/多仓source.json` + `data/final_detail.json` 等 |
| 3 | [make_report.py](vod/make_report.py) | 人读的报告：可用清单、聚合入口、待人工验证 | [output/verify_report.md](vod/output/verify_report.md) |
| 4 | [decode_configs.py](vod/decode_configs.py) | 解码每个仓（4 种加密/包装格式），提取站点列表 | `data/sites_index.json`（原始响应缓存在 `data/cache/`） |
| 5 | [select_12.py](vod/select_12.py) | 按站点内容聚类，选出互不重复的最佳 12 个 | [output/selected_12.json](vod/output/selected_12.json)（每行一个 JSON） |
| 6 | [verify_selected.py](vod/verify_selected.py) | 复查这 12 个是否在线（只打印） | —— |
| 7 | [update_cold_movie.py](vod/update_cold_movie.py) | 12 精选 + 原有条目里仍可用且不重复的 → 发布 | `../HK-IPTV/Cold_Movie.json`（旧版备份到 `data/`） |

```bash
cd vod
python verify_candidates.py                                            # candidates → data/report.json
python verify_candidates.py sources/harvest.json -o data/report2.json  # harvest    → data/report2.json
python build_final.py && python make_report.py
python decode_configs.py && python select_12.py && python verify_selected.py
python update_cold_movie.py
```

[check_tvbox_sources.py](vod/check_tvbox_sources.py) `<多仓.json>` 可单独体检任何 `{"urls": [...]}` 格式的多仓文件，
例如 `python vod/check_tvbox_sources.py vod/output/多仓source.json`。

> `build_final.py` 会优先从 `output/多仓source.json.bak`（最初手工整理的清单）读人工命名；
> 该文件目前不存在，会退回读 `多仓source.json` 本身。

---

## 致谢与声明

- 直播抓取+测速引擎：[Guovin/iptv-api](https://github.com/Guovin/iptv-api)（AGPL-3.0）。
  [iptv_api/config/](iptv_api/config/) 基于该项目的默认配置修改而来，台标 `config/logo/` 也来自该项目。
- 所有直播 / 点播接口均收集自互联网公开分享，随时可能失效，仅供个人学习使用；若有侵权请联系删除。
