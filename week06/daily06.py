# 장 마감 뒤 하루 정리: 그날 분봉 수집 → 실전 차트 → README 5절 표와 날짜별 절 갱신. 주문은 내지 않는다
#   python daily06.py            오늘
#   python daily06.py 20261124   지정한 날 (다시 실행해도 같은 내용으로 덮어쓴다)
# 작업 스케줄러 NH_daily06 이 평일 15:50 에 run_daily06.bat 으로 실행한다 (11/24~11/27)
# 계좌 화면 캡처(screenshots/account_YYYYMMDD.png)는 사람이 한다. 파일이 있으면 링크를 건다
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import data06
import plot06
from data06 import RESULTS

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"
ANALYSIS = "## 6. 결과 분석"
SIDE = {1: "매수", -1: "매도"}


def records(day):
    path = RESULTS / f"journal_{day}.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def crashes(day):
    """run_trade06.bat 이 남긴 오류 종료 줄과 그 직전 예외 메시지"""
    path = RESULTS / "trade_console.log"
    if not path.exists():
        return []
    d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    lines, out = path.read_text(encoding="utf-8", errors="replace").splitlines(), []
    for i, line in enumerate(lines):
        m = re.match(rf"\[{d}\s+(\d+:\d+:\d+)\.\d+\] trade06\.py exit (\d+), restart (\d+)/5", line)
        if m:
            err = next((x.strip() for x in reversed(lines[max(0, i - 30):i]) if "Error" in x and ":" in x), "")
            out.append((m.group(1).zfill(8), f"프로그램 오류 종료(코드 {m.group(2)}) {err}".strip()
                        + f". 1분 뒤 재실행 ({m.group(3)}/5)"))
    return out


def outside_alerts(day):
    """감시 프로그램, 중단 시험이 보낸 알림 (trade06 알림은 journal 에 있다)"""
    path = RESULTS / "alerts.jsonl"
    d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        r = json.loads(line)
        if r["ts"].startswith(d) and r.get("src") != "trade06.py":
            out.append((r["ts"][11:19], f"알림({r['src']}): {r['msg']}"))
    return out


def events(recs, day):
    ev, fails = [], [r for r in recs if r["event"] == "price_fail"]
    starts = [r for r in recs if r["event"] == "start"]
    for i, r in enumerate(starts):
        what = "자동매매 시작" if i == 0 else "자동매매 재실행"
        exp = r["state"]["side"] * r["state"]["lots"]
        ev.append((r["ts"][11:19], f"{what}. 증권사 잔고 {r['broker']}계약, 기록 {exp}계약"
                   + (" 일치" if r["broker"] == exp else " **불일치**")))
    plain = {"skip": lambda r: f"진입 신호 제외: {r['why']} (당일 손익 {r['pnl_today']:+,}원)",
             "alert": lambda r: f"알림: {r['msg']}",
             "stop_moved": lambda r: f"분할 청산 뒤 손절가 이동: {r['stop']} (진입가)",
             "end": lambda r: f"종료 ({r['why']}), 당일 손익 {r['pnl_today']:+,}원"}
    for r in recs:
        e = r["event"]
        if e in plain:
            ev.append((r["ts"][11:19], plain[e](r)))
        elif e in ("order_fail", "order_unknown", "order_error", "exit_failed", "error", "position_fail",
                   "chart_fail", "open_qty_fail", "state_write_fail", "order_wait"):
            detail = r.get("err") or r.get("why") or r.get("reason") or ""
            ev.append((r["ts"][11:19], f"`{e}` {detail}".strip()))
    if fails:
        a, b = fails[0]["ts"][11:16], fails[-1]["ts"][11:16]
        span = a if a == b else f"{a}\\~{b}"
        ev.append((fails[0]["ts"][11:19], f"시세 조회 실패 {len(fails)}회 ({span}). 실패한 확인에서는 손절을 판정하지 않음"))
    ev += crashes(day) + outside_alerts(day)
    return sorted(ev)


def trades(recs):
    enters = [r for r in recs if r["event"] == "enter"]
    exits = [r for r in recs if r["event"] == "exit"]
    rows = ["| 진입 | 방향 | 진입가 | 청산 | 청산가 | 사유 | 손익 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for e in enters:
        tid = f"{datetime.fromisoformat(e['ts']):%m%d %H:%M}"
        xs = [x for x in exits if x["trade"] == tid] or [None]
        for i, x in enumerate(xs):
            head = (f"| {e['ts'][11:16]} | {SIDE[e['side']]} {e['lots']}계약 | {e['px']:.1f} " if i == 0
                    else "| | | ")
            tail = ("| (청산 기록 없음) | | | |" if x is None else
                    f"| {x['ts'][11:16]}, {x['lots']}계약 | {x['exit']:.1f} | {x['reason']} | {x['pnl']:+,}원 |")
            rows.append(head + tail)
    other = [x for x in exits if x["trade"] not in {f"{datetime.fromisoformat(e['ts']):%m%d %H:%M}" for e in enters}]
    for x in other:  # 전일 보유 정리, 이상 정리 등 그날 진입이 아닌 청산
        rows.append(f"| {x['trade']} | {SIDE[x['side']]} | {x['entry']:.1f} | {x['ts'][11:16]}, {x['lots']}계약 "
                    f"| {x['exit']:.1f} | {x['reason']} | {x['pnl']:+,}원 |")
    total = sum(x["pnl"] for x in exits)
    rows.append(f"| **합계** | | | | | | **{total:+,}원** |")
    return rows if enters or exits else ["거래 없음 (진입 신호가 없었거나 진입 조건을 충족하지 않음)"], enters, exits, total


def summary_cell(recs, day):
    c = Counter(r["event"] for r in recs)
    parts = []
    if c["start"] > 1:
        parts.append(f"재실행 {c['start'] - 1}회")
    if crashes(day):
        parts.append(f"오류 종료 {len(crashes(day))}회")
    if c["price_fail"]:
        parts.append(f"시세 조회 실패 {c['price_fail']}회")
    n_fail = sum(c[k] for k in ("order_fail", "order_unknown", "exit_failed"))
    if n_fail:
        parts.append(f"주문 실패 {n_fail}회")
    if c["skip"]:
        parts.append(f"한도로 진입 제외 {c['skip']}회")
    halts = {r["msg"] for r in recs if r["event"] == "alert" and r["msg"].startswith("이상 감지")}
    if halts:
        parts.append(f"이상 감지 {len(halts)}건")
    return ", ".join(parts) or "이상 없음"


def update_readme(day, recs):
    d = datetime.strptime(day, "%Y%m%d")
    md = f"{d.month:02d}/{d.day:02d}"
    rows, enters, exits, total = trades(recs)
    stops = len({x["trade"] for x in exits if x["reason"] == "손절"})
    end = [r for r in recs if r["event"] == "end"]
    pnl = end[-1]["pnl_today"] if end else total
    row = (f"| {md} | {len(enters)} | {stops} | **{pnl:+,}원** | {summary_cell(recs, day)} |" if recs
           else f"| {md} | | | | 실행 기록 없음 |")

    shot = HERE / "screenshots" / f"account_{day}.png"
    lines = [f"#### {md}", ""]
    if (RESULTS / f"fig_live_{day}.png").exists():
        lines += [f"![{md} 실전](results/fig_live_{day}.png)", ""]
    lines += rows + [""]
    lines.append(f"- 계좌 화면: [screenshots/account_{day}.png](screenshots/account_{day}.png)" if shot.exists()
                 else f"- 계좌 화면: 캡처 대기 (`screenshots/account_{day}.png`)")
    lines.append("- 손익은 체결가와 2주차 실측 수수료율로 계산한 추정치다.")
    lines += ["", f"**{md} 실행 기록** (`results/journal_{day}.jsonl`, `trade_console.log`, `alerts.jsonl`에서 자동 정리)", ""]
    lines += [f"- {t} {msg}" for t, msg in events(recs, day)] or ["- 기록 없음"]
    block = "\n".join(lines) + "\n\n"

    s = README.read_text(encoding="utf-8")
    pat = re.compile(rf"^#### {re.escape(md)}\n.*?(?=^#### |^{re.escape(ANALYSIS)})", re.S | re.M)
    old = pat.search(s)
    if old and "자동 정리)" not in old.group(0):  # 직접 작성한 날짜 절(11/23)은 표 줄까지 건드리지 않는다
        sys.exit(f"README {md} 절은 직접 작성한 내용이라 덮어쓰지 않는다")
    s, n = re.subn(rf"^\| {re.escape(md)} \|.*\|$", row, s, count=1, flags=re.M)
    if not n:
        sys.exit(f"README 5절 표에 {md} 줄이 없다")
    s = pat.sub(lambda _: block, s, count=1) if pat.search(s) else s.replace(ANALYSIS, block + ANALYSIS, 1)
    README.write_text(s, encoding="utf-8")
    print("README 갱신:", row)


def main():
    day = next((a for a in sys.argv[1:] if a.isdigit()), f"{datetime.now():%Y%m%d}")
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    recs = records(day)
    if recs:
        data06.fetch(iso, iso)
        plot06.live_day(day)
    update_readme(day, recs)


if __name__ == "__main__":
    main()
