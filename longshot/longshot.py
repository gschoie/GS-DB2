# -*- coding: utf-8 -*-
"""
longshot — 스크롤 캡처 도구 (Windows)

복사가 안 되는 앱(예: 다올FI Pro 뉴스창)의 내용을,
마우스 휠(또는 Page Down 키)을 자동으로 보내면서 반복 캡처하고
겹치는 부분을 자동 감지해 한 장의 긴 이미지로 이어붙인다.
--ocr 옵션을 주면 완성된 이미지에서 텍스트도 추출한다.

사용법:
    python longshot.py            # 영역 드래그 선택 → 자동 스크롤 캡처
    python longshot.py --ocr      # 캡처 후 텍스트(.txt)도 추출
    python longshot.py --help     # 전체 옵션
"""

import argparse
import ctypes
import datetime
import subprocess
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
pyautogui.PAUSE = 0.02

SCRIPT_DIR = Path(__file__).resolve().parent


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


# ---------------------------------------------------------------- 창 활성화

def activate_window_at(x, y):
    """좌표 (x, y) 아래에 있는 창을 앞으로 가져와 포커스를 준다.

    휠/키 입력이 확실히 대상 앱으로 가도록 하기 위한 것.
    클릭하지 않으므로 뉴스 링크가 눌릴 일은 없다.
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        hwnd = user32.WindowFromPoint(POINT(x, y))
        if not hwnd:
            return False
        root_hwnd = user32.GetAncestor(hwnd, 2)  # GA_ROOT
        # 포그라운드 잠금 회피용으로 무해한 Alt 키를 한 번 눌러준다
        pyautogui.press("alt")
        user32.SetForegroundWindow(root_hwnd)
        time.sleep(0.2)
        return True
    except Exception:
        return False


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


def looks_blank(frame):
    """캡처 방지(검은 화면) 또는 빈 화면인지 검사."""
    return float(frame.std()) < 2.0


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


def send_scroll(method, clicks, cx, cy):
    if method == "wheel":
        pyautogui.scroll(-clicks, x=cx, y=cy)
    else:  # pgdn
        pyautogui.press("pagedown")


def scroll_capture(region, args):
    """휠(또는 PgDn)을 보내며 반복 캡처하고 즉석에서 이어붙인다."""
    left, top, width, height = region
    cx = left + width // 2
    cy = top + height // 2

    # 커서를 영역 중앙에 올리고, 그 아래 창을 활성화해 포커스를 확보한다
    pyautogui.moveTo(cx, cy)
    activate_window_at(cx, cy)
    time.sleep(0.3)

    method = "pgdn" if args.method == "pgdn" else "wheel"
    auto = args.method == "auto"
    appended = 0

    with mss.mss() as sct:
        stitched = grab(sct, region)
        if looks_blank(stitched):
            print("경고: 캡처된 화면이 거의 단색입니다.")
            print("  대상 앱에 화면 캡처 방지가 걸려 있거나, 영역 선택이 잘못됐을 수 있습니다.")
        prev = stitched.copy()
        stuck = 0

        for i in range(1, args.max_frames):
            send_scroll(method, args.scroll, cx, cy)
            time.sleep(args.delay)
            frame = grab(sct, region)

            if frames_almost_equal(frame, prev):
                stuck += 1
                if auto and method == "wheel" and stuck >= 2 and appended == 0:
                    # 휠이 전혀 안 먹는 앱 → Page Down 키로 전환해 재시도
                    print("  휠 입력이 반영되지 않아 Page Down 키 방식으로 전환합니다...")
                    method = "pgdn"
                    stuck = 0
                    activate_window_at(cx, cy)
                    continue
                print(f"  [{i}] 화면 변화 없음 ({stuck}/{args.stuck_limit})")
                if stuck >= args.stuck_limit:
                    print("  맨 아래에 도달한 것으로 판단, 종료합니다.")
                    break
                continue
            stuck = 0
            prev = frame.copy()

            # 앱 상단에 고정 헤더가 있으면 잘라낸다
            body = frame[args.fixed_top:] if args.fixed_top > 0 else frame

            y = find_overlap(stitched, body, strip_h=args.strip)
            if y is None:
                # 겹침을 못 찾음 — 스크롤이 한 화면을 넘었을 수 있으니 통째로 붙인다
                print(f"  [{i}] 겹침 미검출 → 프레임 전체 연결 (이음새가 어긋날 수 있음)")
                stitched = np.vstack([stitched, body])
                appended += 1
            elif y >= body.shape[0]:
                stuck += 1
            else:
                stitched = np.vstack([stitched, body[y:]])
                appended += 1
                print(f"  [{i}] +{body.shape[0] - y}px (누적 {stitched.shape[0]}px)")

    if appended == 0:
        print()
        print("한 번도 스크롤이 반영되지 않았습니다. 가능한 원인:")
        print("  1) 대상 앱이 '관리자 권한'으로 실행 중 → run_admin.bat 으로 이 도구도 관리자로 실행")
        print("  2) 캡처 중 다른 창을 클릭해 포커스를 뺏김 → 캡처 중에는 손대지 말 것")
        print("  3) 앱이 휠/PgDn 둘 다 무시 → --method pgdn 또는 --scroll 값을 바꿔 재시도")

    return stitched, appended


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
    ap.add_argument("--method", choices=["auto", "wheel", "pgdn"], default="auto",
                    help="스크롤 방식: auto(기본, 휠→안 먹으면 PgDn), wheel, pgdn")
    ap.add_argument("--scroll", type=int, default=5,
                    help="한 번에 굴릴 휠 클릭 수 (기본 5, 이음새가 어긋나면 줄일 것)")
    ap.add_argument("--delay", type=float, default=0.4,
                    help="스크롤 후 대기 초 (기본 0.4, 앱이 느리면 늘릴 것)")
    ap.add_argument("--max-frames", type=int, default=300,
                    help="최대 캡처 횟수 (기본 300)")
    ap.add_argument("--stuck-limit", type=int, default=4,
                    help="화면 변화 없음이 몇 번 연속이면 종료할지 (기본 4)")
    ap.add_argument("--fixed-top", type=int, default=0,
                    help="영역 상단의 고정 헤더 높이(px) — 매 프레임에서 잘라냄")
    ap.add_argument("--strip", type=int, default=80,
                    help="겹침 검출용 띠 높이(px, 기본 80)")
    ap.add_argument("--countdown", type=int, default=3,
                    help="시작 전 카운트다운 초 (기본 3)")
    ap.add_argument("--ocr", action="store_true",
                    help="캡처 후 이미지에서 텍스트 추출(.txt 저장)")
    ap.add_argument("--out", type=str, default=None,
                    help="저장 경로 (기본: 이 폴더의 captures\\longshot_날짜시간.png)")
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
    stitched, appended = scroll_capture(region, args)

    if args.out:
        out = Path(args.out).resolve()
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = SCRIPT_DIR / "captures" / f"longshot_{stamp}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    ok, buf = cv2.imencode(".png", stitched)  # 경로에 한글이 있어도 안전하게 저장
    if not ok:
        print("PNG 인코딩 실패")
        return 1
    out.write_bytes(buf.tobytes())
    print()
    print(f"저장 완료: {out}")
    print(f"이미지 크기: {stitched.shape[1]}x{stitched.shape[0]}px, 이어붙인 프레임 {appended}개")

    if args.ocr and appended > 0:
        txt = out.with_suffix(".txt")
        print("OCR 실행 중...")
        engine = run_ocr(out, txt)
        if engine:
            print(f"텍스트 저장 완료({engine}): {txt}")
        else:
            print("OCR 엔진이 없습니다.  pip install winocr  후 다시 시도하세요.")

    # 저장된 파일을 탐색기에서 바로 보여준다
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(out)])

    return 0


if __name__ == "__main__":
    sys.exit(main())
