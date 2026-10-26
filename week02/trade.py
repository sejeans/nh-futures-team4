# 2주차 실전: 코스닥150 F 볼린저 평균회귀, 모의계좌 1계약 (params_bollinger.json · 계획 플로우차트 그대로)
# 08:50 실행 → 09:00 부터 매 분 판정 → 15:25 전량 청산 후 종료
# 중간에 다시 실행해도 잔고와 오늘 기록을 읽어 이어 관리한다
# 멈추기: week02 폴더에 STOP 파일을 만들면 다음 분에 청산하고 종료
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from fetch_bars import parse
from nh import NH, NHError, OrderUnknown
from strategy import MULT, P, TICK, bollinger

HERE = Path(__file__).resolve().parent
JOURNAL = HERE / "results" / f"journal_{datetime.now():%Y%m%d}.jsonl"
STOP_FILE = HERE / "STOP"
OPEN_AT = "09:00"                    # 모의계좌 운영 시작 (과제 공지)
GIVE_UP_AT = "15:34"                 # 15:35 종료 단일가 전까지 청산 재시도
ENTRY_FROM, ENTRY_UNTIL = P["entry_window_close_time"]
EXIT_AT = P["force_exit_time"]
STOP_TICKS = P["stop_ticks"]
LOSS_LIMIT = P["daily_loss_limit_krw"]
FEE_KRW = 0     # 1계약 주문 1회당 수수료. 10/26 manual_roundtrip.py 실측값으로 바꾼다
POLL_LAG = 5    # 분이 바뀌고 몇 초 뒤 판정할지 (봉 확정 대기)


def sign(x):
    return (x > 0) - (x < 0)


def decide(hm, five, pos, entry, px, row, pnl_today):
    """한 분의 판정. 플로우차트 순서: 15:25 → 손절 → 중심선 → 진입. 반환 ("exit", 사유) / ("enter", ±1) / None
    hm = 판정 시각(봉 마감), five = 5분봉 마감 여부, row = 그 봉의 strategy.bollinger 행"""
    if pos:
        if hm >= EXIT_AT:
            return "exit", "15:25"
        if round((px - entry) * sign(pos) / TICK) <= -STOP_TICKS:
            return "exit", "손절"
        if five and row is not None and row["exit_long" if pos > 0 else "exit_short"]:
            return "exit", "중심선"
        return None
    if (five and row is not None and row["entry"] and ENTRY_FROM <= hm < ENTRY_UNTIL
            and pnl_today > -LOSS_LIMIT):
        return "enter", int(row["entry"])
    return None


def journal(event, **kw):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **kw}
    line = json.dumps(rec, ensure_ascii=False, default=str)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if event != "tick":
        print(line, flush=True)


def realized_today():
    if not JOURNAL.exists():
        return 0
    recs = [json.loads(line) for line in JOURNAL.read_text(encoding="utf-8").splitlines()]
    return sum(r["pnl"] for r in recs if r["event"] == "exit")


def wait_next_minute():
    now = datetime.now()
    boundary = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    time.sleep(max(0.0, (boundary + timedelta(seconds=POLL_LAG) - now).total_seconds()))
    return boundary


def snapshot(nh):
    """현재가(손절 판정용) + 기록용 베이시스·외국인 (계획 5-1-1). 기록용 실패는 매매를 멈추지 않는다"""
    p = nh.price()
    snap = {k: p.get(k) for k in ("last_pric", "spt_pric", "theo_pric", "fact_bas", "theo_bas", "dev_rt", "opint")}
    try:
        snap["frgn_net_buy"] = nh.trend_investor().get("frgn_net_buy")
    except Exception as e:  # noqa: BLE001
        snap["frgn_err"] = repr(e)
    return float(p["last_pric"]), snap


def signal_row(nh, boundary):
    b5 = parse(nh.chart_minute(dcnt=5, req_qty=60)["Occurs1"], 5)  # 60봉 = 전일 봉 포함 (carry_over)
    b5 = b5[b5.close_t <= boundary]                                   # 확정된 봉만
    sig = bollinger(b5)
    return sig.loc[boundary] if boundary in sig.index else None


def send(nh, side, qty, why):
    """시장가 주문 → 잔고로 결과 확인. 응답이 없어도 재주문하지 않는다 (운영안내 22p). 반환: 포지션, 평균가, 체결"""
    try:
        b = nh.price_bid()["Occurs1"][0]
        book = {"ask": b["occurs1_ask_best_pric"], "bid": b["occurs1_bid_best_pric"]}
    except Exception as e:  # noqa: BLE001
        book = {"err": repr(e)}
    ord_no = None
    try:
        res = nh.order(side, qty)
        ord_no = res["ord_no"].strip()
        journal("order", why=why, side=side, qty=qty, ord_no=ord_no, msg=res.get("msg_cntn"), book=book)
    except OrderUnknown as e:
        journal("order_unknown", why=why, side=side, qty=qty, err=str(e), book=book)
    except NHError as e:
        journal("order_rejected", why=why, side=side, qty=qty, err=str(e), book=book)
    time.sleep(1)
    fill = nh.find_fill(ord_no) if ord_no else None
    pos, avg = nh.position()
    journal("fill", ord_no=ord_no, fill=fill, pos=pos, avg=avg)
    return pos, avg, fill


def main():
    selfcheck()
    nh = NH()
    if nh.env != "paper":
        sys.exit("NH_ENV=paper 에서만 실행한다")
    pos, entry = nh.position()
    pnl = realized_today()
    journal("start", pos=pos, entry=entry, pnl_today=pnl, stop_ticks=STOP_TICKS, loss_limit=LOSS_LIMIT, fee=FEE_KRW)

    while True:
        boundary = wait_next_minute()
        hm = boundary.strftime("%H:%M")
        if hm < OPEN_AT:
            continue
        try:
            if STOP_FILE.exists() and pos == 0:
                journal("end", why="STOP 파일", pnl_today=pnl)
                break
            px, snap = snapshot(nh)
            five = boundary.minute % 5 == 0
            row = signal_row(nh, boundary) if five else None
            if five and row is None:
                journal("bar_lag", hm=hm)  # 봉이 아직 안 들어옴 → 이번 5분은 판정하지 않는다
            journal("tick", hm=hm, px=px, pos=pos, entry=entry, pnl_today=pnl, **snap,
                    sig=None if row is None else int(row["entry"]))

            act = ("exit", "STOP") if STOP_FILE.exists() and pos else decide(hm, five, pos, entry, px, row, pnl)
            if act and act[0] == "exit":
                prev_pos, prev_entry = pos, entry
                pos, entry, fill = send(nh, -sign(prev_pos), abs(prev_pos), act[1])
                if pos == 0:
                    exit_px = fill["px"] if fill and fill["px"] else px
                    gain = round((exit_px - prev_entry) * sign(prev_pos) * abs(prev_pos) * MULT
                                 - 2 * FEE_KRW * abs(prev_pos))
                    pnl += gain
                    journal("exit", reason=act[1], side=sign(prev_pos), entry=prev_entry, exit=exit_px,
                            pnl=gain, pnl_today=pnl)
                else:
                    journal("exit_failed", reason=act[1], pos=pos)  # 다음 분에 다시 판정된다
            elif act and act[0] == "enter":
                pos, entry, _ = send(nh, act[1], 1, "진입")
                journal("enter" if pos else "enter_failed", side=act[1], entry=entry, pos=pos)

            if hm >= EXIT_AT and pos == 0:
                journal("end", why="15:25", pnl_today=pnl)
                break
            if hm >= GIVE_UP_AT and pos:
                journal("end", why="청산 실패 — 직접 확인 필요", pos=pos)
                sys.exit(1)
        except Exception as e:  # noqa: BLE001  한 분 실패로 루프를 멈추지 않는다
            journal("error", hm=hm, err=repr(e))


def selfcheck():
    row = {"entry": 1, "exit_long": False, "exit_short": False}
    s = STOP_TICKS * TICK
    assert decide("10:00", True, 0, None, 1000, row, 0) == ("enter", 1)
    assert decide("10:01", False, 0, None, 1000, row, 0) is None               # 5분봉 마감 아니면 진입 없음
    assert decide("08:55", True, 0, None, 1000, row, 0) is None                # 진입 시간 전
    assert decide("15:25", True, 0, None, 1000, row, 0) is None                # 진입 시간 후
    assert decide("10:00", True, 0, None, 1000, row, -LOSS_LIMIT) is None      # 일일 한도
    assert decide("10:01", False, 1, 1000, 1000 - s + TICK, row, 0) is None    # 손절 1틱 전
    assert decide("10:01", False, 1, 1000, 1000 - s, row, 0) == ("exit", "손절")
    assert decide("10:01", False, -1, 1000, 1000 + s, row, 0) == ("exit", "손절")
    assert decide("15:25", False, 1, 1000, 1000, row, 0) == ("exit", "15:25")
    assert decide("10:05", True, 1, 1000, 1001, {**row, "exit_long": True}, 0) == ("exit", "중심선")
    assert decide("10:05", True, -1, 1000, 999, {**row, "exit_long": True}, 0) is None


if __name__ == "__main__":
    main()
