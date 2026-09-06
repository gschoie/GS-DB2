"""유튜브 3일 모음 → 대시보드 페이지.

수집·발송은 Apps Script(gas/youtube_defense_bot.gs)가 한다. 그쪽이 텔레그램으로
모음을 보낸 뒤 같은 내용을 workflow_dispatch 입력으로 넘겨 주면, 이 스크립트가
대시보드에 남길 파일을 만든다.

  telegram_research_dashboard/static/youtube_digest/<날짜>.html   화면
  telegram_research_dashboard/static/youtube_digest/<날짜>.md     NotebookLM 업로드용
  telegram_research_dashboard/static/youtube_digest/<날짜>.txt    주소만 (복사용)
  telegram_research_dashboard/static/youtube_digest_report.html   날짜 선택 인덱스

입력(JSON):
  {"date": "2026-08-28", "from": "2026-08-25",
   "channels": [{"name": "샤를세환",
                 "videos": [{"t": "제목", "u": "주소", "p": "2026-08-26T12:00:00Z"}]}]}

표준 라이브러리만 쓴다.
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9), name="KST")
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "telegram_research_dashboard" / "static"

# 두 종류의 모음이 같은 골격을 쓴다. payload 의 kind 로 갈린다.
KINDS = {
    "digest": {
        "dir": "youtube_digest",
        "index": "youtube_digest_report.html",
        "title": "방산 유튜브 3일 모음",
        "sub": "3일마다 07:00",
    },
    "weekly": {
        "dir": "youtube_weekly",
        "index": "youtube_weekly_report.html",
        "title": "방산 유튜브 주간 모음",
        "sub": "평일 아침 · 지난 7일 (쇼츠·라이브 제외)",
    },
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PAGE_CSS = """
:root{color-scheme:dark}
body{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.75;font-size:15px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:21px;color:#e8edf5;margin:0 0 4px}
.meta{color:#8b96a8;font-size:12.5px;margin-bottom:22px}
h2{font-size:16.5px;color:#7fb4ff;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #223046}
a{color:#6aa8ff;text-decoration:none}a:hover{text-decoration:underline}
ul{margin:6px 0;padding-left:22px}
li{margin:4px 0}
li .when{color:#8b96a8;font-size:12.5px;margin-left:6px}
.copybox{margin:26px 0 0}
.copybox textarea{width:100%;box-sizing:border-box;height:190px;background:#161d29;color:#d8dee9;
  border:1px solid #2c3a52;border-radius:10px;padding:12px;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:12.5px;line-height:1.65;resize:vertical}
.copybox .row{display:flex;gap:10px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.copybox h2{margin:0;border:none;padding:0;flex:1;min-width:180px}
button{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}
button:hover{border-color:#3d5175}
.hint{color:#8b96a8;font-size:12.5px;margin:8px 0 0}
"""


def load_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"입력이 JSON이 아닙니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("입력의 최상위가 객체가 아닙니다.")

    date = str(payload.get("date") or "").strip()
    if not DATE_RE.match(date):
        # 날짜를 안 줬거나 모양이 틀렸으면 오늘(KST)로 둔다 — 페이지 하나 때문에 멈출 일은 아니다.
        date = datetime.now(KST).strftime("%Y-%m-%d")
    payload["date"] = date

    channels = []
    for group in payload.get("channels") or []:
        if not isinstance(group, dict):
            continue
        videos = [
            {
                "t": str(video.get("t") or "").strip() or "(제목 없음)",
                "u": str(video.get("u") or "").strip(),
                "p": str(video.get("p") or "").strip(),
            }
            for video in (group.get("videos") or [])
            if isinstance(video, dict) and str(video.get("u") or "").strip()
        ]
        if videos:
            channels.append({"name": str(group.get("name") or "(채널 미상)"), "videos": videos})
    payload["channels"] = channels
    return payload


def when_label(stamp: str) -> str:
    if not stamp:
        return ""
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(KST).strftime("%m-%d %H:%M")


def all_urls(channels: list) -> list:
    return [video["u"] for group in channels for video in group["videos"]]


def grouped_urls(channels: list) -> str:
    """복사용 주소 목록 — 텔레그램 둘째 통과 같은 모양(채널 이름 밑에 그 채널 주소들)."""
    blocks = []
    for group in channels:
        lines = [f"[{group['name']}]"]
        lines.extend(video["u"] for video in group["videos"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_markdown(payload: dict, cfg: dict) -> str:
    channels = payload["channels"]
    total = len(all_urls(channels))
    lines = [
        f"# {cfg['title']} {payload['date']}",
        "",
        f"- 채널 {len(channels)}개 · 영상 {total}건",
    ]
    if payload.get("from"):
        lines.append(f"- 대상 구간: {payload['from']} ~ {payload['date']} (KST)")
    lines.append("")
    for group in channels:
        lines.append(f"## {group['name']}")
        lines.append("")
        for video in group["videos"]:
            label = when_label(video["p"])
            suffix = f" · {label}" if label else ""
            lines.append(f"- [{video['t']}]({video['u']}){suffix}")
        lines.append("")
    lines.append("## 주소만")
    lines.append("")
    lines.append(grouped_urls(channels))
    lines.append("")
    return "\n".join(lines)


def render_page(payload: dict, cfg: dict) -> str:
    channels = payload["channels"]
    urls = all_urls(channels)
    date = payload["date"]

    body = [
        '<div class="wrap">',
        f"<h1>📺 {cfg['title']} · {html.escape(date)}</h1>",
    ]
    meta = f"채널 {len(channels)}개 · 영상 {len(urls)}건"
    if payload.get("from"):
        meta += f" · {html.escape(str(payload['from']))} ~ {html.escape(date)} (KST)"
    body.append(f'<p class="meta">{meta}</p>')

    for group in channels:
        body.append(f"<h2>{html.escape(group['name'])}</h2>")
        body.append("<ul>")
        for video in group["videos"]:
            label = when_label(video["p"])
            when = f'<span class="when">{label}</span>' if label else ""
            body.append(
                f'<li><a href="{html.escape(video["u"])}" target="_blank" rel="noopener">'
                f"{html.escape(video['t'])}</a>{when}</li>"
            )
        body.append("</ul>")

    body.extend([
        '<div class="copybox">',
        '<div class="row">',
        "<h2>주소만 — NotebookLM 소스에 붙여넣기</h2>",
        '<button id="copy">전체 복사</button>',
        f'<a href="{html.escape(date)}.md" download>⬇ .md</a>',
        "</div>",
        f'<textarea id="urls" readonly>{html.escape(grouped_urls(channels))}</textarea>',
        '<p class="hint">NotebookLM은 자막이 있는 공개 영상만 소스로 받습니다. '
        "자막 없는 영상은 추가 단계에서 거절됩니다.</p>",
        "</div>",
        "</div>",
        "<script>",
        "document.getElementById('copy').onclick=function(){",
        "  var t=document.getElementById('urls');t.select();",
        "  document.execCommand('copy');",
        "  this.textContent='복사됨 ✓';var b=this;setTimeout(function(){b.textContent='전체 복사'},1500);",
        "};",
        "</script>",
    ])

    return (
        '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{cfg['title']} {html.escape(date)}</title>"
        f"<style>{PAGE_CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


def render_index(dates: list, cfg: dict) -> str:
    latest = dates[0] if dates else ""
    kind_dir = cfg["dir"]
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{cfg['title']}</title><style>
:root{{color-scheme:dark}}
body{{margin:0;padding:16px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif}}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px;color:#e8edf5}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
.bar a.bundle{{color:#7fb4ff;font-size:12.5px;text-decoration:none;border:1px solid #2c3a52;
  border-radius:8px;padding:7px 12px}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #223046;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>📺 {cfg['title']} <small style="font-size:11px;color:#8b96a8">{cfg['sub']}</small></h1>
  <a class="bundle" id="mdlink" href="{kind_dir}/{latest}.md" download title="NotebookLM 업로드용 마크다운">⬇ .md</a>
  <button id="prev" title="이전 회차">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 회차">▶</button>
</div>
<iframe id="frame" title="유튜브 3일 모음"></iframe>
<script>
const DATES={json.dumps(dates, ensure_ascii=False)};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='{kind_dir}/'+sel.value+'.html';document.getElementById('mdlink').href='{kind_dir}/'+sel.value+'.md'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 모음이 없습니다 — 자동 생성을 기다리는 중.</body>';
</script></body></html>
"""


def known_dates(out_dir: Path) -> list:
    if not out_dir.is_dir():
        return []
    dates = {p.stem for p in out_dir.glob("*.html") if DATE_RE.match(p.stem)}
    return sorted(dates, reverse=True)


def reindex(kind: str) -> None:
    cfg = KINDS[kind]
    out_dir = STATIC / cfg["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dates = known_dates(out_dir)
    (STATIC / cfg["index"]).write_text(render_index(dates, cfg), encoding="utf-8")
    print(f"{kind} 인덱스 갱신 — 회차 {len(dates)}개")


def main() -> int:
    cli = argparse.ArgumentParser(description="유튜브 3일 모음 대시보드 페이지 생성")
    cli.add_argument("--payload-file", help="JSON 파일 경로. 없으면 표준입력에서 읽는다")
    cli.add_argument("--reindex-only", action="store_true",
                     help="새 회차 없이 인덱스만 다시 만든다 (두 종류 모두)")
    args = cli.parse_args()

    if args.reindex_only:
        for kind in KINDS:
            reindex(kind)
        return 0

    raw = (
        Path(args.payload_file).read_text(encoding="utf-8")
        if args.payload_file
        else sys.stdin.read()
    )
    payload = load_payload(raw)
    kind = str(payload.get("kind") or "digest")
    if kind not in KINDS:
        print(f"모르는 kind '{kind}' — digest 로 처리합니다.")
        kind = "digest"
    cfg = KINDS[kind]
    out_dir = STATIC / cfg["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    if not payload["channels"]:
        print("영상이 없어 페이지를 만들지 않습니다 — 인덱스만 갱신합니다.")
    else:
        date = payload["date"]
        (out_dir / f"{date}.html").write_text(render_page(payload, cfg), encoding="utf-8")
        (out_dir / f"{date}.md").write_text(render_markdown(payload, cfg), encoding="utf-8")
        (out_dir / f"{date}.txt").write_text(
            grouped_urls(payload["channels"]) + "\n", encoding="utf-8"
        )
        total = len(all_urls(payload["channels"]))
        print(f"[{kind}] {date}: 채널 {len(payload['channels'])}개 · 영상 {total}건 기록")

    reindex(kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
