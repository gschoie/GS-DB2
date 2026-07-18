# -*- coding: utf-8 -*-
"""로컬 편의 오케스트레이터: 수집 → 감지 → 리포트 → (텔레그램).
  python run.py               # 수집·감지·리포트 (텔레그램은 미리보기만)
  python run.py --send        # 텔레그램 실제 발송까지
  python run.py --no-fetch    # 수집 건너뛰고 기존 스냅샷으로 감지·리포트만
GitHub Actions는 각 단계를 개별 스텝으로 실행하므로 이 파일에 의존하지 않는다.
"""
import sys, argparse, subprocess, os

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def step(title, args):
    print(f"\n=== {title} ===")
    subprocess.run([sys.executable] + args, cwd=HERE, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="텔레그램 실제 발송")
    ap.add_argument("--no-fetch", action="store_true", help="수집 생략(기존 스냅샷 사용)")
    a = ap.parse_args()
    if not a.no_fetch:
        step("스냅샷 수집", ["fetch_holdings.py"])
    step("변화 감지", ["detect_changes.py"])
    step("리포트 생성", ["build_report.py"])
    step("텔레그램", ["telegram_notify.py"] + ([] if a.send else ["--dry-run"]))
    print("\n완료.")


if __name__ == "__main__":
    main()
