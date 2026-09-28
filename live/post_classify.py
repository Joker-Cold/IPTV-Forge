"""
Regroup iptv_api's result by region: merge the per-topic HK/MO/TW groups from
user_demo.txt into one group each, and sort ♻️未匹配频道 into continents using
iptv-org's channel database plus name heuristics.

Usage:  python post_classify.py [input.m3u] [output.m3u]
Defaults: ../iptv_api/output/cold_result.m3u -> output/COLD_result.m3u
"""
import json
import os
import re
import sys
import time
import urllib.request


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, '..', 'iptv_api', 'output', 'cold_result.m3u')
DEFAULT_DST = os.path.join(HERE, 'output', 'COLD_result.m3u')

CACHE_FILE = os.path.expanduser('~/.cache/iptv_org_channels.json')
CACHE_TTL = 7 * 86400
IPTV_ORG_URL = 'https://iptv-org.github.io/api/channels.json'

DEFAULT_GROUP = '🌏亚洲其他'
HK_GROUP = '🇭🇰香港'
MO_GROUP = '🇲🇴澳门'
TW_GROUP = '🇹🇼台湾'
TIME_GROUP = '🕘️更新时间'
UNMATCH_GROUP = '♻️未匹配频道'

MERGE_MAP = {
    '📺香港综合': HK_GROUP,
    '📰香港新闻财经': HK_GROUP,
    '🏀香港体育': HK_GROUP,
    '🎬香港影视': HK_GROUP,
    '🎰澳门频道': MO_GROUP,
    '📡台湾新闻': TW_GROUP,
    '📺台湾综合': TW_GROUP,
    '🎭台湾戏剧电影': TW_GROUP,
    '🌏台湾其他': TW_GROUP,
}

CONTINENT_LABEL = {
    'AS': '🌏亚洲',
    'EU': '🌍欧洲',
    'AF': '🌍非洲',
    'NA': '🌎北美洲',
    'SA': '🌎南美洲',
    'OC': '🌏大洋洲',
    'HK': HK_GROUP,
    'MO': MO_GROUP,
    'TW': TW_GROUP,
    'AS_OTHER': DEFAULT_GROUP,
    'GLOBAL': DEFAULT_GROUP,
}

GROUP_ORDER = [
    HK_GROUP, MO_GROUP, TW_GROUP,
    '🌏亚洲', '🌎北美洲', '🌍欧洲', '🌎南美洲', '🌍非洲', '🌏大洋洲',
    DEFAULT_GROUP,
]

CONTINENT = {
    'JP': 'AS', 'KR': 'AS', 'KP': 'AS', 'IN': 'AS', 'PK': 'AS', 'BD': 'AS',
    'LK': 'AS', 'NP': 'AS', 'BT': 'AS', 'MV': 'AS', 'AF': 'AS', 'IR': 'AS',
    'IQ': 'AS', 'SA': 'AS', 'AE': 'AS', 'QA': 'AS', 'BH': 'AS', 'KW': 'AS',
    'OM': 'AS', 'YE': 'AS', 'JO': 'AS', 'IL': 'AS', 'PS': 'AS', 'LB': 'AS',
    'SY': 'AS', 'TR': 'AS', 'CY': 'AS', 'GE': 'AS', 'AM': 'AS', 'AZ': 'AS',
    'KZ': 'AS', 'UZ': 'AS', 'TM': 'AS', 'KG': 'AS', 'TJ': 'AS', 'TH': 'AS',
    'VN': 'AS', 'LA': 'AS', 'KH': 'AS', 'MM': 'AS', 'MY': 'AS', 'SG': 'AS',
    'ID': 'AS', 'PH': 'AS', 'BN': 'AS', 'TL': 'AS', 'MN': 'AS',
    'CN': 'AS_OTHER', 'HK': 'HK', 'MO': 'MO', 'TW': 'TW',
    'GB': 'EU', 'IE': 'EU', 'FR': 'EU', 'DE': 'EU', 'IT': 'EU', 'ES': 'EU',
    'PT': 'EU', 'NL': 'EU', 'BE': 'EU', 'LU': 'EU', 'CH': 'EU', 'AT': 'EU',
    'LI': 'EU', 'MC': 'EU', 'AD': 'EU', 'SM': 'EU', 'VA': 'EU', 'MT': 'EU',
    'SE': 'EU', 'NO': 'EU', 'DK': 'EU', 'FI': 'EU', 'IS': 'EU', 'EE': 'EU',
    'LV': 'EU', 'LT': 'EU', 'PL': 'EU', 'CZ': 'EU', 'SK': 'EU', 'HU': 'EU',
    'RO': 'EU', 'BG': 'EU', 'GR': 'EU', 'RS': 'EU', 'HR': 'EU', 'SI': 'EU',
    'BA': 'EU', 'ME': 'EU', 'MK': 'EU', 'AL': 'EU', 'XK': 'EU', 'MD': 'EU',
    'UA': 'EU', 'BY': 'EU', 'RU': 'EU', 'FO': 'EU', 'GI': 'EU', 'IM': 'EU',
    'JE': 'EU', 'GG': 'EU',
    'EG': 'AF', 'LY': 'AF', 'TN': 'AF', 'DZ': 'AF', 'MA': 'AF', 'EH': 'AF',
    'SD': 'AF', 'SS': 'AF', 'ET': 'AF', 'ER': 'AF', 'DJ': 'AF', 'SO': 'AF',
    'KE': 'AF', 'UG': 'AF', 'TZ': 'AF', 'RW': 'AF', 'BI': 'AF', 'MW': 'AF',
    'MZ': 'AF', 'ZM': 'AF', 'ZW': 'AF', 'BW': 'AF', 'NA': 'AF', 'ZA': 'AF',
    'LS': 'AF', 'SZ': 'AF', 'MG': 'AF', 'MU': 'AF', 'SC': 'AF', 'KM': 'AF',
    'RE': 'AF', 'YT': 'AF', 'AO': 'AF', 'CD': 'AF', 'CG': 'AF', 'CF': 'AF',
    'TD': 'AF', 'CM': 'AF', 'GQ': 'AF', 'GA': 'AF', 'ST': 'AF', 'NG': 'AF',
    'NE': 'AF', 'BJ': 'AF', 'TG': 'AF', 'GH': 'AF', 'CI': 'AF', 'BF': 'AF',
    'ML': 'AF', 'MR': 'AF', 'SN': 'AF', 'GM': 'AF', 'GW': 'AF', 'GN': 'AF',
    'SL': 'AF', 'LR': 'AF', 'CV': 'AF',
    'US': 'NA', 'CA': 'NA', 'MX': 'NA', 'GT': 'NA', 'BZ': 'NA', 'SV': 'NA',
    'HN': 'NA', 'NI': 'NA', 'CR': 'NA', 'PA': 'NA', 'CU': 'NA', 'JM': 'NA',
    'HT': 'NA', 'DO': 'NA', 'PR': 'NA', 'TT': 'NA', 'BB': 'NA', 'BS': 'NA',
    'GD': 'NA', 'LC': 'NA', 'VC': 'NA', 'AG': 'NA', 'DM': 'NA', 'KN': 'NA',
    'BM': 'NA', 'GL': 'NA', 'KY': 'NA', 'VI': 'NA', 'VG': 'NA',
    'BR': 'SA', 'AR': 'SA', 'CL': 'SA', 'PE': 'SA', 'CO': 'SA', 'VE': 'SA',
    'EC': 'SA', 'BO': 'SA', 'PY': 'SA', 'UY': 'SA', 'GY': 'SA', 'SR': 'SA',
    'GF': 'SA', 'FK': 'SA',
    'AU': 'OC', 'NZ': 'OC', 'FJ': 'OC', 'PG': 'OC', 'SB': 'OC', 'VU': 'OC',
    'NC': 'OC', 'PF': 'OC', 'WS': 'OC', 'TO': 'OC', 'KI': 'OC', 'TV': 'OC',
    'NR': 'OC', 'PW': 'OC', 'FM': 'OC', 'MH': 'OC', 'CK': 'OC', 'NU': 'OC',
    'GU': 'OC', 'MP': 'OC',
    'INT': 'GLOBAL',
}


SCRIPT_RULES = [
    (re.compile(r'[\u0400-\u04FF]'), 'EU'),
    (re.compile(r'[\uAC00-\uD7AF]'), 'AS'),
    (re.compile(r'[\u3040-\u30FF]'), 'AS'),
    (re.compile(r'[\u0E00-\u0E7F]'), 'AS'),
    (re.compile(r'[\u0900-\u097F]'), 'AS'),
    (re.compile(r'[\u0590-\u05FF]'), 'AS'),
    (re.compile(r'[\u0370-\u03FF]'), 'EU'),
    (re.compile(r'[\u0600-\u06FF]'), 'AS'),
]


KEYWORD_RULES = [
    (re.compile(
        r'CCTV|央视|卫视|凤凰|湖南|浙江|江苏|东方卫视|北京|广东|福建|河南|河北|'
        r'山东|山西|安徽|江西|湖北|黑龙江|吉林|辽宁|内蒙古|新疆|西藏|青海|甘肃|'
        r'宁夏|陕西|四川|重庆|云南|贵州|海南|兵团|XJTV|GDTV|央广|中国教育|'
        r'求索|金鹰|嘉佳|优漫|纪实|哒啵|嘉佳|靖天|靖洋|惠州|深圳|上海|天津|'
        r'桂林|哈尔滨|大连|青岛|宁波|苏州|杭州|南京|成都|武汉|沈阳|长沙|郑州|'
        r'济南|合肥|南昌|福州|厦门|昆明|贵阳|兰州|西安|海口|三亚|乌鲁木齐|拉萨|'
        r'呼和浩特|长春|银川|西宁|太原|石家庄|南宁|公共频道|新闻频道|经济频道|'
        r'生活频道|文体频道|影视频道|科教频道|少儿频道|都市频道|国际频道|综合频道',
        re.I), 'AS_OTHER'),
    (re.compile(r'\b(Sydney|Melbourne|Adelaide|Brisbane|Perth|Canberra|ABC AU|2GB|3AW|'
                r'Channel 9 AU|Seven Network|Network 10|SBS Australia|Foxtel|NITV)\b', re.I), 'OC'),
    (re.compile(r'\b(Auckland|Wellington|TVNZ|Sky NZ|Maori TV|RNZ)\b', re.I), 'OC'),
    (re.compile(r'\b(Zee|Sony SAB|Sony TV|Star Plus|Star Jalsha|Star Sports India|Colors|'
                r'Aaj Tak|NDTV|Sun TV|&TV|&pictures|&flix|Sahara|DD News|Doordarshan|ETV|'
                r'Asianet|Republic TV|Times Now|India TV|ABP News|Mirror Now|Pitaara|Sathiyam)\b', re.I), 'AS'),
    (re.compile(r'\b(BBC|ITV|Sky News|Channel 4|Channel 5|Sky Sports|Sky Cinema|Dave UK|UKTV)\b', re.I), 'EU'),
    (re.compile(r'\b(TF1|France [0-9]|M6|Canal\+|Arte|BFM|LCI|RMC|Gulli|Téva|TFX|TMC|6ter|W9|'
                r'France Info|Mangas|TiJi|Cstar)\b', re.I), 'EU'),
    (re.compile(r'\b(ARD|ZDF|RTL|RTL2|ProSieben|Sat\.?1|Sat1|WDR|NDR|BR|HR|MDR|SWR|RBB|'
                r'VOX|Kabel Eins|n-tv|Welt|Tagesschau|Deutsche Welle|DW)\b', re.I), 'EU'),
    (re.compile(r'\b(RAI|Mediaset|TGcom|Italia 1|Italia [0-9]|Canale 5|Rete 4|La7|Sky Italia|TG[0-9]|'
                r'20 Mediaset|27 Twenty|Telepace|Cine34)\b', re.I), 'EU'),
    (re.compile(r'\b(TVE|Telecinco|Antena 3|laSexta|Cuatro|Movistar|Atresmedia|3Cat|'
                r'TV3 Cataluña|TVG|ETB|Canal Sur|Telemadrid)\b', re.I), 'EU'),
    (re.compile(r'\b(Polsat|TVP|TVN(?!Z)|Polonia|Polsat Sport|Eska TV)\b', re.I), 'EU'),
    (re.compile(r'\b(SVT|TV4 Sweden|TV3 Sweden|Kanal 5|SVT[0-9])\b', re.I), 'EU'),
    (re.compile(r'\b(NRK|TV2 Norway|TVNorge)\b', re.I), 'EU'),
    (re.compile(r'\b(DR1|DR2|DR3|DR Ramasjang|TV2 Denmark)\b', re.I), 'EU'),
    (re.compile(r'\b(YLE|MTV3|Nelonen)\b', re.I), 'EU'),
    (re.compile(r'\b(NPO|RTL Nederland|SBS6|Net5|Veronica)\b', re.I), 'EU'),
    (re.compile(r'\b(VRT|VTM|VIER|VIJF|Eén|Canvas|RTBF|La Une|La Deux)\b', re.I), 'EU'),
    (re.compile(r'\b(SRF|RTS|RSI|3\+|Schweiz)\b', re.I), 'EU'),
    (re.compile(r'\b(ORF|Servus TV|Puls 4)\b', re.I), 'EU'),
    (re.compile(r'\b(TRT|ATV|Kanal D|Show TV|Star TV|NTV Turkey|Habertürk|CNN Türk|Fox Turkey|TV8)\b', re.I), 'AS'),
    (re.compile(r'\b(3ABN|TBN|EWTN|Daystar|Inspiration TV|Hillsong|GodTV|Pluto TV|Tubi|Roku|'
                r'CNN|MSNBC|Fox News|HBO|Showtime|Bravo|Lifetime|A&E|History|TLC|Discovery US|'
                r'Animal Planet|Cartoon Network|Nickelodeon|Disney US|MTV USA|VH1|Hallmark|'
                r'30A|WFTT|WFTX|Newsmax|OAN|C-SPAN|PBS|NBC|CBS|ABC US|Fox 5|CBSN|NBCLX)\b', re.I), 'NA'),
    (re.compile(r'\b(Telemundo|Univision|Galavisión|UniMás|Estrella TV|TUDN|ViX)\b', re.I), 'NA'),
    (re.compile(r'\b(CBC|CTV|Global TV|TVA|Radio-Canada|RDS|TSN|Sportsnet|City TV|YES TV|OMNI)\b', re.I), 'NA'),
    (re.compile(r'\b(Televisa|TV Azteca|Canal 5 Mexico|Las Estrellas|Imagen Televisión|Multimedios)\b', re.I), 'NA'),
    (re.compile(r'\b(Globo|SBT|Bandeirantes|Record TV|RedeTV|TV Cultura|TV Brasil|CazeTV)\b', re.I), 'SA'),
    (re.compile(r'\b(Telefe|TV Pública|América TV|El Trece|Canal 9 Argentina|TN Argentina)\b', re.I), 'SA'),
    (re.compile(r'\b(Mega Chile|Canal 13|Chilevisión|TVN Chile|13C|13 Teleseries|13 Festival)\b', re.I), 'SA'),
    (re.compile(r'\b(Caracol|RCN|Señal Colombia|Canal Uno)\b', re.I), 'SA'),
    (re.compile(r'\b(América TV Peru|Latina TV|Panamericana TV|ATV Peru)\b', re.I), 'SA'),
    (re.compile(r'\b(RTP|SIC|TVI|Porto Canal|RTP Internacional|RTP África)\b', re.I), 'EU'),
    (re.compile(r'\b(Al Jazeera|Al Arabiya|MBC|Rotana|LBC|Dubai TV|Abu Dhabi|Sama Dubai|'
                r'Saudi 24|Bahrain TV|Kuwait TV|Oman TV|Qatar TV|Sharjah TV|Al Mayadeen|Al Hurra|'
                r'Al Iqraa|Iqraa|Al Alamiya|Sada TV|Majid)\b', re.I), 'AS'),
    (re.compile(r'\b(IRIB|IRINN|Press TV|Manoto)\b', re.I), 'AS'),
    (re.compile(r'\b(KBS|MBC Korea|SBS Korea|YTN|JTBC|TVN Korea|Channel A|MBN|tvN|EBS|Mnet)\b', re.I), 'AS'),
    (re.compile(r'\b(NHK|TV Asahi|Fuji TV|TBS Japan|TV Tokyo|Nippon TV|WOWOW)\b', re.I), 'AS'),
    (re.compile(r'\b(Thai PBS|TPBS|Channel 3 Thailand|Channel 7 Thailand|Workpoint TV|GMM 25|'
                r'13 Siam|Amarin TV|Mono 29|Nation TV)\b', re.I), 'AS'),
    (re.compile(r'\b(SCTV|RCTI|MNCTV|Trans TV|Trans 7|Indosiar|Metro TV|TVRI|Kompas TV|tvOne)\b', re.I), 'AS'),
    (re.compile(r'\b(GMA|ABS-CBN|TV5 Philippines|ANC|UNTV|PTV|GMA News TV)\b', re.I), 'AS'),
    (re.compile(r'\b(Astro|TV1 Malaysia|TV2 Malaysia|TV3 Malaysia|TV9 Malaysia|RTM|Bernama)\b', re.I), 'AS'),
    (re.compile(r'\b(CNA|Channel 5 Singapore|Channel 8 Singapore|Mediacorp|Suria|Vasantham)\b', re.I), 'AS'),
    (re.compile(r'\b(VTV|HTV Vietnam|VTC|VOV|HanoiTV)\b', re.I), 'AS'),
    (re.compile(r'\b(SuperSport|SABC|eNCA|eTV|Mzansi|M-Net|kykNET|Kingdomsat|1KZN)\b', re.I), 'AF'),
    (re.compile(r'\b(NTA|Channels TV|Africa Magic|ON TV Nigeria|Arise News|TVC News)\b', re.I), 'AF'),
    (re.compile(r'\b(2M Maroc|Medi1 TV|Al Aoula|Hespress|2M Monde)\b', re.I), 'AF'),
    (re.compile(r'\b(Magyar Televízió|MTVA|Duna TV|RTL Klub|TV2 Hungary|M[0-9] Magyar|16tv Budapest)\b', re.I), 'EU'),
    (re.compile(r'\b(ČT|Česká|Nova CZ|Prima)\b', re.I), 'EU'),
    (re.compile(r'\b(STV Slovakia|Markíza|JOJ)\b', re.I), 'EU'),
    (re.compile(r'\b(HRT|Nova TV Croatia|RTL Hrvatska)\b', re.I), 'EU'),
    (re.compile(r'\b(RTS|B92|Pink TV|Prva Srpska|Happy TV|BRT 3|24Kitchen Serbia)\b', re.I), 'EU'),
    (re.compile(r'\b(ERT|Mega Greece|ANT1|Star Greece|Alpha TV|Skai)\b', re.I), 'EU'),
    (re.compile(r'\b(TVR|Antena 1 Romania|Pro TV|Kanal D Romania|Digi24)\b', re.I), 'EU'),
    (re.compile(r'\b(bTV|Nova Bulgaria|BNT)\b', re.I), 'EU'),
    (re.compile(r'\b(Discovery|National Geographic|History Channel|Cartoon|Disney|MTV|Nick|'
                r'Animal Planet|Boomerang|Eurosport|Euronews|Bloomberg|CNBC|TRACE|TV5Monde|France 24)\b',
                re.I), 'GLOBAL'),
]


def fetch_iptv_org():
    if os.path.exists(CACHE_FILE) and time.time() - os.path.getmtime(CACHE_FILE) < CACHE_TTL:
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    req = urllib.request.Request(IPTV_ORG_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    data = json.loads(raw)
    with open(CACHE_FILE, 'wb') as f:
        f.write(raw)
    return data


_NOISE_BRACKET = re.compile(r'\[[^\]]*\]|\([^)]*\)')
_NOISE_QUALITY = re.compile(r'\b(HD|SD|FHD|UHD|4K|8K|HEVC)\b', re.I)
_KEEP_CHARS = re.compile(
    r'[^0-9A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff'
    r'\u0600-\u06ff\u0e00-\u0e7f\u0900-\u097f\u0590-\u05ff\u0370-\u03ff]+'
)


def normalize(name):
    s = _NOISE_BRACKET.sub('', name)
    s = _NOISE_QUALITY.sub('', s)
    s = _KEEP_CHARS.sub('', s)
    return s.lower()


GENERIC_KEYS = {
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
    'live', 'tvlive', 'news', 'tvnews', 'music', 'tvmusic', 'movies', 'tvmovies',
    'kids', 'tvkids', 'sports', 'tvsports', 'family', 'tvfamily', 'entertainment',
    'cinema', 'tvcinema', 'comedy', 'drama', 'documentary', 'classic', 'classics',
    'plus', 'star', 'sun', 'sky', 'channel', 'tv', 'radio', 'culture', 'life',
    'lifestyle', 'health', 'travel', 'food', 'home', 'garden', 'fun', 'prime',
    'express', 'today', 'mtvclassic', 'mtvhits', 'mtv', 'vh1', 'national',
    'natgeo', 'natgeowild', 'natgeographic', 'nationalgeographic',
    'nationalgeographicwild', 'discovery', 'discoverychannel', 'animal',
    'animalplanet', 'cartoon', 'cartoonnetwork', 'nick', 'nickelodeon',
    'disney', 'disneychannel', 'history', 'historychannel', 'tlc', 'hbo',
    'showtime', 'pluto', 'tubi', 'roku', 'xumo', 'peacock', 'fox', 'fox5',
    'fox8', 'foxnews', 'cnn', 'msnbc', 'public', 'international', 'world',
    'global', 'europe', 'asia', 'africa', 'america', 'american', 'pacific',
    'central', 'east', 'west', 'north', 'south', 'crime', 'thriller', 'horror',
    'sci_fi', 'scifi', 'action', 'love', 'romance', 'gold', 'silver', 'bronze',
    'platinum', 'diamond', 'red', 'blue', 'green', 'black', 'white',
}


def build_lookup(channels):
    by_key = {}
    for c in channels:
        country = c.get('country')
        if not country:
            continue
        names = [c.get('name', '')] + (c.get('alt_names') or [])
        for n in names:
            k = normalize(n)
            if not k or len(k) < 4 or k in GENERIC_KEYS:
                continue
            by_key.setdefault(k, set()).add(country)
    m = {}
    for k, cs in by_key.items():
        if len(cs) == 1:
            m[k] = ('CC', next(iter(cs)))
        else:
            conts = {CONTINENT.get(c) for c in cs}
            conts.discard(None)
            conts.discard('AS_OTHER')
            conts.discard('GLOBAL')
            if len(conts) == 1:
                m[k] = ('CONT', next(iter(conts)))
    return m


def classify(name, lookup):
    for pat, cat in KEYWORD_RULES:
        if pat.search(name):
            return CONTINENT_LABEL[cat]
    norm = normalize(name)
    if norm and norm in lookup:
        kind, val = lookup[norm]
        if kind == 'CC':
            cat = CONTINENT.get(val, 'AS_OTHER')
        else:
            cat = val
        return CONTINENT_LABEL.get(cat, DEFAULT_GROUP)
    for pat, cat in SCRIPT_RULES:
        if pat.search(name):
            return CONTINENT_LABEL[cat]
    return DEFAULT_GROUP


_GROUP_PATTERN = re.compile(r'group-title="([^"]*)",')
_NAME_PATTERN = re.compile(r'group-title="[^"]*",(.+)$')


def _group_match(extinf):
    return _GROUP_PATTERN.search(extinf)


def _rewrite_group(extinf, new_group):
    m = _group_match(extinf)
    if not m:
        return extinf
    return extinf[:m.start()] + f'group-title="{new_group}",' + extinf[m.end():]


def process(infile, outfile):
    """Returns {group: channel count} of what was written."""
    channels = fetch_iptv_org()
    lookup = build_lookup(channels)
    print(f'[INFO] iptv-org channels: {len(channels)}, lookup keys: {len(lookup)}')

    with open(infile, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header = []
    raw_blocks = []
    pending = None
    for line in lines:
        if line.startswith('#EXTM3U'):
            header.append(line)
            continue
        if line.startswith('#EXTINF'):
            pending = line
        elif pending is not None and line.strip():
            raw_blocks.append((pending, line))
            pending = None

    time_block = None
    items = []
    stats = {}
    for idx, (ext, url) in enumerate(raw_blocks):
        gm = _group_match(ext)
        old_group = gm.group(1) if gm else ''
        nm = _NAME_PATTERN.search(ext.rstrip('\n'))
        name = nm.group(1).strip() if nm else ''

        if old_group == TIME_GROUP:
            time_block = (ext, url)
            continue

        if old_group == UNMATCH_GROUP:
            new_group = classify(name, lookup)
            is_reclass = True
        else:
            new_group = MERGE_MAP.get(old_group, old_group)
            is_reclass = False

        new_ext = _rewrite_group(ext, new_group) if new_group != old_group else ext
        items.append((new_group, is_reclass, idx, name, new_ext, url))
        stats[new_group] = stats.get(new_group, 0) + 1

    order_map = {g: i for i, g in enumerate(GROUP_ORDER)}
    items.sort(key=lambda x: (
        order_map.get(x[0], 999),
        1 if x[1] else 0,
        x[3].lower() if x[1] else x[2],
    ))

    with open(outfile, 'w', encoding='utf-8') as f:
        for h in header:
            f.write(h)
        if time_block:
            f.write(time_block[0])
            f.write(time_block[1])
        for _, _, _, _, ext, url in items:
            f.write(ext)
            f.write(url)

    total = sum(stats.values())
    print(f'[INFO] Processed {total} entries:')
    for g in GROUP_ORDER:
        if g in stats:
            print(f'  {g}: {stats[g]}')
    for g, n in stats.items():
        if g not in order_map:
            print(f'  {g}: {n}')
    return stats


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    dst = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DST
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    process(src, dst)


if __name__ == '__main__':
    main()
