# -*- coding: utf-8 -*-
"""
longshot — 스크롤 캡처 도구 (Windows)

복사가 안 되는 앱(예: 다올FI Pro 뉴스창)의 내용을,
마우스 휠을 자동으로 굴리면서 반복 캡처하고
겹치는 부분을 자동 감지해 한 장의 긴 이미지로 이어붙인다.
--ocr 옵션을 주면 완성된 이미지에서 텍스트도 추출한다.

사용법:
    python longshot.py            # 영역 드래그 선택 → 자동 스크롤 캡처
    python longshot.py --ocr      # 캡처 후 텍스트(.txt)도 추출
    python longshot.py --help     # 전체 옵션
"""

import argparse
import datetime
import sys
import time
from pathlib import Path

import numpy as np

try:
    import cv2
    import mss
    import pyautogui
except ImportError as e:
    print(f"필수 패키지가 없습니다: {e.name}")
    print("설치:  pip install -r requirements.txt")
    sys.exit(1)

pyautogui.FAILSAFE = True  # 마우스를 화면 왼쪽 위 모서리로 던지면 즉시 중단


# ---------------------------------------------------------------- 영역 선택

def select_region():
    """반투명 전체 화면 오버레이를 띄우고 드래그로 캡처 영역을 고른다.

    다중 모니터를 지원한다(가상 데스크톱 전체를 덮음).
    반환: (left, top, width, height) — 절대 좌표.
    """
    import tkinter as tk

    with mss.mss() as sct:
        virt = sct.monitors[0]  # 모든 모니터를 합친 가상 화면

    sel = {}

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{virt['width']}x{virt['height']}+{virt['left']}+{virt['top']}")
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
    root.configure(bg="black")

    canvas = tk.Canvas(root, cursor="cross", bg="gray20", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_text(
        virt["width"] // 2, 60,
        text="캡처할 영역을 드래그하세요  (ESC: 취소)",
        fill="white", font=("Malgun Gothic", 20, "bold"),
    )

    state = {"x0": 0, "y0": 0, "rect": None}

    def on_press(ev):
        state["x0"], state["y0"] = ev.x, ev.y
        state["rect"] = canvas.create_rectangle(
            ev.x, ev.y, ev.x, ev.y, outline="red", width=3
        )

    def on_drag(ev):
        canvas.coords(state["rect"], state["x0"], state["y0"], ev.x, ev.y)

    def on_release(ev):
        x0, y0 = state["x0"], state["y0"]
        x1, y1 = ev.x, ev.y
        sel["left"] = virt["left"] + min(x0, x1)
        sel["top"] = virt["top"] + min(y0, y1)
        sel["width"] = abs(x1 - x0)
        sel["height"] = abs(y1 - y0)
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda ev: root.destroy())

    root.mainloop()

    if not sel or sel["width"] < 50 or sel["height"] < 50:
        return None
    return sel["left"], sel["top"], sel["width"], sel["height"]


# ---------------------------------------------------------------- 캡처/합성

def grab(sct, region):
    """region=(l, t, w, h) 영역을 BGR numpy 배열로 캡처."""
    left, top, width, height = region
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    img = np.asarray(shot)[:, :, :3]  # BGRA → BGR
    return np.ascontiguousarray(img)


def frames_almost_equal(a, b, tol=1.0):
    """두 프레임이 사실상 같은가(스크롤이 더 안 됐는가)."""
    if a.shape != b.shape:
        return False
    return float(np.mean(cv2.absdiff(a, b))) < tol


def find_overlap(stitched, frame, strip_h=80, min_conf=0.85):
    """합성본의 맨 아래 strip_h픽셀 띠를 새 프레임 안에서 찾는다.

    반환: 새 프레임에서 '새로운 내용'이 시작되는 y좌표, 또는 None(매칭 실패).
    """
    strip_h = min(strip_h, stitched.shape[0] - 1, frame.shape[0] - 1)
    template = stitched[-strip_h:]
    res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < min_conf:
        return None
    return max_loc[1] + strip_h


def scroll_capture(region, scroll_clicks, delay, max_frames, fixed_top, strip_h):
    """휠을 굴리며 반복 캡처하고 즉석에서 이어붙인다."""
    left, top, width, height = region
    cx = left + width // 2
    cy = top + height // 2

    # 휠 이벤트가 대상 창으로 가도록 커서를 영역 중앙에 올려 둔다.
    # (Windows 10+ 기본 설정은 '커서 아래 창'이 휠을 받으므로 클릭은 하지 않는다)
    pyautogui.moveTo(cx, cy)
    time.sleep(0.3)

    with mss.mss() as sct:
        stitched = grab(sct, region)
        prev = stitched.copy()
        stuck = 0

        for i in range(1, max_frames):
            pyautogui.scroll(-scroll_clicks, x=cx, y=cy)
            time.sleep(delay)
            frame = grab(sct, region)

            if frames_almost_equal(frame, prev):
                stuck += 1
                print(f"  [{i}] 화면 변화 없음 ({stuck}/3)")
                if stuck >= 3:
                    print("  맨 아래에 도달한 것으로 판단, 종료합니다.")
                    break
                continue
            stuck = 0
            prev = frame.copy()

            # 앱 상단에 고정 헤더가 있으면 잘라낸다
            body = frame[fixed_top:] if fixed_top > 0 else frame

            y = find_overlap(stitched, body, strip_h=strip_h)
            if y is None:
                # 겹침을 못 찾음 — 스크롤이 한 화면을 넘었을 수 있으니 통째로 붙인다
                print(f"  [{i}] 겹침 미검출 → 프레임 전체 연결 (이음새가 어긋날 수 있음)")
                stitched = np.vstack([stitched, body])
            elif y >= body.shape[0]:
                stuck += 1
            else:
                stitched = np.vstack([stitched, body[y:]])
                print(f"  [{i}] +{body.shape[0] - y}px (누적 {stitched.shape[0]}px)")

    return stitched


# ---------------------------------------------------------------- OCR

def run_ocr(image_path, txt_path):
    """캡처 이미지에서 텍스트 추출. winocr(Windows 내장 OCR) 우선, 없으면 pytesseract."""
    img_bgr = cv2.imread(str(image_path))

    # 1) Windows 내장 OCR — 한국어 언어팩만 있으면 추가 설치 불필요
    try:
        import asyncio
        import winocr
        from PIL import Image

        pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        result = asyncio.run(winocr.recognize_pil(pil, lang="ko"))
        text = "\n".join(line.text for line in result.lines)
        txt_path.write_text(text, encoding="utf-8")
        return "winocr"
    except ImportError:
        pass
    except Exception as e:
        print(f"  winocr 실패({e}) → pytesseract 시도")

    # 2) Tesseract (별도 설치 필요: https://github.com/UB-Mannheim/tesseract/wiki)
    try:
        import pytesseract

        text = pytesseract.image_to_string(img_bgr, lang="kor+eng")
        txt_path.write_text(text, encoding="utf-8")
        return "pytesseract"
    except ImportError:
        return None


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="자동 스크롤 캡처 → 긴 이미지 저장 (+선택적 OCR)"
    )
    ap.add_argument("--region", type=int, nargs=4, metavar=("L", "T", "W", "H"),
                    help="캡처 영역 절대좌표 (생략 시 드래그로 선택)")
    ap.add_argument("--scroll", type=int, default=3,
                    help="한 번에 굴릴 휠 클릭 수 (기본 3, 이음새가 어긋나면 줄일 것)")
    ap.add_argument("--delay", type=float, default=0.6,
                    help="스크롤 후 대기 초 (기본 0.6, 앱이 느리면 늘릴 것)")
    ap.add_argument("--max-frames", type=int, default=200,
                    help="최대 캡처 횟수 (기본 200)")
    ap.add_argument("--fixed-top", type=int, default=0,
                    help="영역 상단의 고정 헤더 높이(px) — 매 프레임에서 잘라냄")
    ap.add_argument("--strip", type=int, default=80,
                    help="겹침 검출용 띠 높이(px, 기본 80)")
    ap.add_argument("--countdown", type=int, default=3,
                    help="시작 전 카운트다운 초 (기본 3)")
    ap.add_argument("--ocr", action="store_true",
                    help="캡처 후 이미지에서 텍스트 추출(.txt 저장)")
    ap.add_argument("--out", type=str, default=None,
                    help="저장 경로 (기본: 바탕화면 longshot_날짜시간.png)")
    args = ap.parse_args()

    if args.region:
        region = tuple(args.region)
    else:
        print("캡처할 영역을 드래그로 선택하세요...")
        region = select_region()
        if region is None:
            print("선택이 취소되었거나 영역이 너무 작습니다.")
            return 1
    print(f"영역: left={region[0]} top={region[1]} w={region[2]} h={region[3]}")
    print(f"(다음부터는  --region {region[0]} {region[1]} {region[2]} {region[3]}  으로 바로 시작 가능)")

    for s in range(args.countdown, 0, -1):
        print(f"  {s}초 후 시작 — 대상 창이 가려지지 않게 해주세요...")
        time.sleep(1)

    print("캡처 시작 (중단: 마우스를 화면 왼쪽 위 모서리로 이동)")
    stitched = scroll_capture(
        region,
        scroll_clicks=args.scroll,
        delay=args.delay,
        max_frames=args.max_frames,
        fixed_top=args.fixed_top,
        strip_h=args.strip,
    )

    if args.out:
        out = Path(args.out)
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        desktop = Path.home() / "Desktop"
        out = (desktop if desktop.exists() else Path.cwd()) / f"longshot_{stamp}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    ok, buf = cv2.imencode(".png", stitched)  # 경로에 한글이 있어도 안전하게 저장
    if not ok:
        print("PNG 인코딩 실패")
        return 1
    out.write_bytes(buf.tobytes())
    print(f"\n저장 완료: {out}  ({stitched.shape[1]}x{stitched.shape[0]}px)")

    if args.ocr:
        txt = out.with_suffix(".txt")
        print("OCR 실행 중...")
        engine = run_ocr(out, txt)
        if engine:
            print(f"텍스트 저장 완료({engine}): {txt}")
        else:
            print("OCR 엔진이 없습니다.  pip install winocr  후 다시 시도하세요.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
