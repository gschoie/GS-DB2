"""주보 5종의 '차트 목록'을 한 곳에서 만든다 — 어떤 그림이 있고 그 안에 어떤 선(종목·묶음 지수)이 있는가.

종목 정의는 **다른 곳에 있는 정본을 빌려 쓴다**(목록을 두 곳에 두면 어긋난다 — 유튜브 채널 목록 교훈):
  - 주가변동표·INDEX : 별도 리포 ecos-fx-rates 의 생성기 모듈(peergroup/weekly_*_image.py)을 import.
    경로는 ECOS_DIR(워크플로가 public 리포를 clone 해 둔 폴더). 그 모듈들은 맨 위에서 matplotlib 를
    import 하는데 여기선 그림을 안 그리므로, matplotlib 가 없으면 가짜 모듈을 꽂아 종목 정의만 읽는다.
  - 수급.그림 : 이 리포 coverage_flow/build_report.WEEKLY_GROUPS + universe.csv/chart_universe.csv 이름.
  - 컨센서스 : ecos consensus/weekly_consensus_chart.COMPANIES (ast 로 리터럴만 읽는다 — 그 모듈은 import 때
    matplotlib 백엔드를 고르고 폰트를 만지므로 import 하지 않는다).
  - ER : CSV 자체에 sector·name 이 있어 목록이 필요 없다.
"""
from __future__ import annotations

import ast
import csv
import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ECOS_DIR = os.environ.get("ECOS_DIR") or os.path.join(REPO, "_ecos")

# 갤러리 페이지(대시보드) 주소 — 꼽힌 차트에서 원본 그림으로 건너가는 링크
PEER_PAGE = {"ship": "peer_price.html", "defense": "peer_price.html?u=defense,construction",
             "construction": "peer_price.html?u=defense,construction"}
INDEX_PAGE = {"ship": "ship_index.html", "defense": "ship_index.html?u=defense",
              "construction": "ship_index.html?u=construction"}
UNIVERSE_LABEL = {"ship": "조선·해운·에너지", "defense": "방산·항공우주", "construction": "건설기계"}
FLOW_PAGE = {"ship": "coverage_flow_report.html#weekly-ship", "parts": "coverage_flow_report.html#weekly-parts",
             "defense": "coverage_flow_report.html#weekly-defense", "construction": "coverage_flow_report.html#weekly-construction"}


def _stub_matplotlib():
    """matplotlib 가 없을 때만 — 생성기 모듈의 `import matplotlib / matplotlib.use("Agg") / from matplotlib import …`
    를 통과시키는 빈 모듈. 그림 함수는 호출하지 않으므로 속성은 전부 아무 일도 안 하는 더미."""
    try:
        import matplotlib  # noqa: F401
        return
    except ImportError:
        pass

    class _Any:
        def __call__(self, *a, **k):
            return self

        def __getattr__(self, name):
            return self

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            return _Any()

    for name in ("matplotlib", "matplotlib.pyplot", "matplotlib.font_manager", "matplotlib.patches",
                 "matplotlib.dates", "matplotlib.ticker"):
        sys.modules.setdefault(name, _Mod(name))


def _ecos_modules():
    pg = os.path.join(ECOS_DIR, "peergroup")
    if not os.path.isdir(pg):
        raise FileNotFoundError(f"ecos-fx-rates 체크아웃이 없다: {pg} (ECOS_DIR 로 지정)")
    _stub_matplotlib()
    if pg not in sys.path:
        sys.path.insert(0, pg)
    base = importlib.import_module("weekly_peer_price_image")
    ship = importlib.import_module("weekly_peer_index_image")
    dfn = importlib.import_module("weekly_defense_index_image")
    con = importlib.import_module("weekly_construction_index_image")
    return base, ship, dfn, con


def _section_file(i, sec):
    """생성기 main() 의 섹션 낱장 파일명 규칙 그대로(확장자 제외)."""
    return sec.get("file") or f"{i:02d}_{sec['title'].replace(' / ', '_').replace('/', '_').replace(' ', '')}"


def peer_sections():
    """주가변동표 — 유니버스 3개 × 섹션(= 갤러리의 낱장 그림 1개). 각 섹션의 행 = (그룹, 표시명, 티커)."""
    base, *_ = _ecos_modules()
    out = []
    for uni, u in base.UNIVERSES.items():
        for i, sec in enumerate(u["sections"], 1):
            rows = [(g, name, t) for g, items in sec["groups"] for name, t in items]
            out.append({"universe": uni, "key": f"peer:{uni}:{_section_file(i, sec)}", "title": sec["title"],
                        "stock": sec.get("market_cap", True), "rows": rows,
                        "file": _section_file(i, sec), "dir": os.path.basename(u["out_dir"]),
                        "link": PEER_PAGE[uni]})
    return out


def _single(items):
    return [{"name": n, "kind": "single", "items": [(n, t)]} for n, t in items]


def _indices(groups):
    return [{"name": g, "kind": "index", "items": list(items)} for g, items in groups.items()]


def index_charts():
    """INDEX 비교 — 유니버스 3개 × 그림 4개. 선 = 종목 하나(single) 또는 시총가중 묶음(index).
    구성은 생성기의 chart1~4/render 와 같아야 한다(그림을 바꾸면 여기도)."""
    base, ship, dfn, con = _ecos_modules()
    charts = []

    def add(uni, no, title, file, lines):
        charts.append({"universe": uni, "key": f"index:{uni}:{file}", "no": no, "title": title, "file": file,
                       "dir": os.path.basename(getattr(ship, "OUT_DIR", "") or base.UNIVERSES[uni]["out_dir"]),
                       "link": INDEX_PAGE[uni], "lines": lines})

    kospi_name, kospi_t = ship.KOSPI
    add("ship", 1, "한국 주식시장 vs. 조선주", ship.OUT_ONE[0],
        [{"name": kospi_name, "kind": "single", "items": [(kospi_name, kospi_t)]},
         {"name": "한국 조선주 (시총가중)", "kind": "index", "items": list(ship.KR_SHIP)}])
    add("ship", 2, f"한국 조선 {len(ship.KR_SHIP)}사 Performance", ship.OUT_ONE[1], _single(ship.KR_SHIP))
    add("ship", 3, "한/중/일/싱 조선주 비교 (시총가중)", ship.OUT_ONE[2], _indices(ship.GROUPS))
    add("ship", 4, "조선 5사 vs. 엔진 vs. 조선기자재 (시총가중)", ship.OUT_ONE[3], _indices(ship.CHAIN))

    add("defense", 1, f"한국 방산 체계 {len(dfn.KR_PRIME)}사 Performance", dfn.OUT_ONE[0], _single(dfn.KR_PRIME))
    add("defense", 2, "한국 방산 부체계(부품) Performance", dfn.OUT_ONE[1], _single(dfn.KR_SUB))
    add("defense", 3, "한국 체계·부체계 vs. 미국·유럽 (시총가중)", dfn.OUT_ONE[2], _indices(dfn.GROUPS))
    add("defense", 4, "드론 · 엔진/부품 · 항공 · 우주 (글로벌, 시총가중)", dfn.OUT_ONE[3], _indices(dfn.THEMES))

    add("construction", 1, "HD건설기계 · 두산밥캣 · 한국 건설기계 부품사", con.OUT_ONE[0],
        _single(con.KR_OEM) + [{"name": "한국 건기 부품사 (시총가중)", "kind": "index", "items": list(con.KR_PARTS)}])
    add("construction", 2, "한국 2사 vs. 미국 · 중국 · 일본 피어 (시총가중)", con.OUT_ONE[1], _indices(con.GROUPS))
    add("construction", 3, "대형 OEM — HD건설기계 · CAT · 일본 · 중국", con.OUT_ONE[2], _single(con.BIG))
    add("construction", 4, "소형·농기계 — 두산밥캣 · Deere · CNH · Kobelco · 대동", con.OUT_ONE[3], _single(con.SMALL))
    # dir 은 유니버스별 출력 폴더(ship 은 peer_price, 나머지는 각 모듈 OUT_DIR)
    for c in charts:
        c["dir"] = os.path.basename({"ship": base.UNIVERSES["ship"]["out_dir"], "defense": dfn.OUT_DIR,
                                     "construction": con.OUT_DIR}[c["universe"]])
    return charts


def flow_groups():
    """수급.그림 — coverage_flow 위클리 묶음(코드 목록) + 이름표."""
    cf = os.path.join(REPO, "coverage_flow")
    if cf not in sys.path:
        sys.path.insert(0, cf)
    br = importlib.import_module("build_report")
    names = {}
    for fn in ("universe.csv", "chart_universe.csv"):
        with open(os.path.join(cf, fn), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                names[r["code"].strip()] = r["name"].strip()
    return [{"key": f"flow:{g['key']}", "group": g["key"], "title": g["title"], "codes": list(g["codes"]),
             "link": FLOW_PAGE.get(g["key"], "coverage_flow_report.html#weekly")} for g in br.WEEKLY_GROUPS], names


def consensus_companies():
    """컨센서스(조방기) — ecos consensus/weekly_consensus_chart.py 의 COMPANIES 리터럴: [(섹터, 이름, 코드)]."""
    path = os.path.join(ECOS_DIR, "consensus", "weekly_consensus_chart.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "COMPANIES" for t in node.targets):
            return [tuple(x) for x in ast.literal_eval(node.value)]
    raise ValueError("COMPANIES 를 찾지 못했다: " + path)


def all_price_tickers(peer, index):
    out = []
    for s in peer:
        out += [t for _, _, t in s["rows"]]
    for c in index:
        for ln in c["lines"]:
            out += [t for _, t in ln["items"]]
    return list(dict.fromkeys(out))


def index_tickers(index):
    """시총이 필요한 티커 = 묶음 지수(index) 안의 종목만."""
    out = []
    for c in index:
        for ln in c["lines"]:
            if ln["kind"] == "index":
                out += [t for _, t in ln["items"]]
    return list(dict.fromkeys(out))
