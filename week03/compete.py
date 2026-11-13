# 11/13 해외 모의 수익률 대회용: TSMOM 12개월 방향으로 ZN 24계약, 15:00 진입 → 손절 10틱 또는 17:55 청산
# 사용: python compete.py            (15:00 까지 기다렸다가 시작, 주문 전 y 확인 1번)
#       python compete.py --yes      (묻지 않음)   --dry  (주문 없이 판단만 기록)
#       --start 15:00 --end 17:55 --qty 24 --stop 10   (리허설 때 바꿀 수 있음)
# 안 멈추기: 매 바퀴 예외를 잡고 5초 뒤 다시 돈다. 잔고를 매번 증권사에서 다시 읽어 목표 수량과 맞춘다(재시작해도 같은 판단).
# 중복 주문 방지: 주문 응답이 없으면(OrderUnknown) 15초 기다린 뒤 잔고로 다시 판단한다.
# 손절·청산 후에는 다시 진입하지 않는다(results/compete_state.json). 비상 청산: week03 폴더에 STOP 파일을 만든다.
# 모의계좌 전용 (nh.py 가 실주문 차단). 신호 계산은 trend_live.py / strategies.py 와 같은 함수.
import argparse
import json
import time
from datetime import datetime

from strategies import adjust, daily, roll_days, tsmom  # 먼저: nh_os 가 week02 를 sys.path 앞에 넣는다
from fetch_bars import RESULTS, save
from nh_os import HERE, SPEC, ZN, NHOverseas, OrderUnknown, _nh

TICK, TICK_USD = SPEC["ZN"]["tick"], SPEC["ZN"]["tick_usd"]
LOOP_SEC = 5
STATE = RESULTS / "compete_state.json"
STOP_FILE = HERE / "STOP"


def stop_hit(side, entry, px, stop_ticks):
    """청산 쪽 호가(매수 보유=매수호가, 매도 보유=매도호가)가 진입가보다 stop_ticks 이상 불리하면 True"""
    return round((px - entry) * side / TICK, 6) <= -stop_ticks


def target(hm, start, end, side, qty, st):
    """지금 가져야 할 순포지션. None = 아직 시작 전(아무것도 안 함)"""
    if hm < start:
        return None
    if hm >= end or st["stopped"] or st["done"] or STOP_FILE.exists():
        return 0
    return side * qty


def rem_qty(rows, ord_no):
    """주문내역에서 그 주문의 미체결 잔량. 거부(9)는 0, 내역에 아직 없으면 None"""
    key = str(ord_no).strip().lstrip("0")
    for r in rows:
        if r.get("occurs1_ord_no", "").strip().lstrip("0") == key:
            return 0 if r.get("occurs1_ord_sts", "").strip() == "9" else int(float(r.get("occurs1_ord_rem_qty") or 0))
    return None


def filled_since(rows, day, start):
    """오늘 start 이후 ZN 체결이 있었나. 상태 파일 없이(다른 PC) 재시작해도 진입했던 걸 안다"""
    hhmm = start.replace(":", "")
    return any(r.get("occurs1_sym", "").strip() == ZN and r.get("occurs1_ord_dt") == day
               and r.get("occurs1_ord_rcv_tm", "")[8:12] >= hhmm and float(r.get("occurs1_exec_qty") or 0) > 0
               for r in rows)


def selfcheck():
    # 11/11 리허설 주문내역 실제 행(634는 접수 직후 미체결 순간, 553은 전체체결)
    rows = [{"occurs1_ord_no": "0000000634", "occurs1_ord_sts": "3", "occurs1_ord_rem_qty": "0000024",
             "occurs1_sym": "ZNZ26", "occurs1_ord_dt": "20261111", "occurs1_ord_rcv_tm": "20261111175500",
             "occurs1_exec_qty": "0000000"},
            {"occurs1_ord_no": "0000000553", "occurs1_ord_sts": "6", "occurs1_ord_rem_qty": "0000000",
             "occurs1_sym": "ZNZ26", "occurs1_ord_dt": "20261111", "occurs1_ord_rcv_tm": "20261111150004",
             "occurs1_exec_qty": "0000024"}]
    assert rem_qty(rows, "634") == 24 and rem_qty(rows, "0000000553") == 0 and rem_qty(rows, "1") is None
    assert filled_since(rows, "20261111", "15:00") and not filled_since(rows, "20261111", "15:01")
    assert not filled_since(rows, "20261112", "15:00")
    t = TICK
    assert stop_hit(-1, 107.0, 107.0 + 10 * t, 10) and not stop_hit(-1, 107.0, 107.0 + 9 * t, 10)
    assert stop_hit(1, 107.0, 107.0 - 10 * t, 10) and not stop_hit(1, 107.0, 107.0 + 30 * t, 10)
    st = {"stopped": False, "done": False}
    assert target("14:59", "15:00", "17:55", -1, 24, st) is None
    assert target("15:00", "15:00", "17:55", -1, 24, st) == -24
    assert target("17:55", "15:00", "17:55", -1, 24, st) == 0
    assert target("16:00", "15:00", "17:55", -1, 24, {**st, "stopped": True}) == 0


def signal(nh, now):
    """직전 완성 일봉 기준 TSMOM 12개월 (+1 매수 / -1 매도 / 0 없음). 오늘 봉은 진행 중이라 뺀다"""
    path = save(f"bars_ZN_cont_1d_{now:%Y%m%d_%H%M}.json", nh.chart_daily(ZN, cidx="1"))
    d = daily("ZN", path, until=f"{now:%Y-%m-%d}")
    c = adjust(d, roll_days(d, TICK)).close
    return int(tsmom(c).iloc[-1]), {"last_bar": f"{c.index[-1]:%Y-%m-%d}", "close_adj": c.iloc[-1],
                                    "date_252_ago": f"{c.index[-253]:%Y-%m-%d}", "close_252_ago": c.iloc[-253]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="15:00")
    ap.add_argument("--end", default="17:55")
    ap.add_argument("--qty", type=int, default=24)
    ap.add_argument("--stop", type=int, default=10, help="손절 틱")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    selfcheck()
    if STOP_FILE.exists() and datetime.fromtimestamp(STOP_FILE.stat().st_mtime).date() < datetime.now().date():
        return print(f"{STOP_FILE} 가 예전 날짜에 만들어져 남아 있다. 이대로면 진입하지 않는다. 지우고 다시 실행")

    nh = NHOverseas()
    today = f"{datetime.now():%Y%m%d}"
    logf = RESULTS / f"compete_{today}.jsonl"

    def log(event, **kw):
        rec = {"at": datetime.now().isoformat(timespec="milliseconds"), "event": event, **_nh._mask(kw)}
        with open(logf, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        print(f"[{rec['at'][11:19]}] {event} {json.dumps(_nh._mask(kw), ensure_ascii=False, default=str)[:300]}", flush=True)

    st = {"date": today, "side": None, "entry": None, "entered": False, "stopped": False, "done": False,
          "last_ord": None}
    if STATE.exists():
        old = json.loads(STATE.read_text(encoding="utf-8"))
        if old.get("date") == today:
            st = old
            log("재시작: 상태 복구", state=st)

    def keep():
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    if st["side"] is None:
        while True:  # 신호 조회도 실패하면 다시 시도
            try:
                st["side"], info = signal(nh, datetime.now())
                log("신호", side=st["side"], **info)
                break
            except Exception as e:  # noqa: BLE001 — 멈추지 않는 게 우선
                log("신호 조회 실패", err=repr(e))
                time.sleep(10)
        keep()
    side = st["side"]
    if not side:
        return log("신호 0: 거래하지 않음")
    log("설정", side=side, qty=a.qty, stop=a.stop, start=a.start, end=a.end, dry=a.dry)
    if not (a.yes or a.dry) and input(f"\n>>> {a.start}에 {ZN} {'매수' if side > 0 else '매도'} {a.qty}계약, "
                                      f"손절 {a.stop}틱, {a.end} 청산. y: ").strip().lower() != "y":
        return log("중단 (y 아님)")

    last_status = 0.0
    while True:
        try:
            now = datetime.now()
            hm = f"{now:%H:%M}"
            tgt = target(hm, a.start, a.end, side, a.qty, st)
            if tgt is None:
                if time.time() - last_status > 60:
                    log("대기", until=a.start)
                    last_status = time.time()
                time.sleep(LOOP_SEC)
                continue
            pos, avg = nh.position(ZN)
            if st.get("last_ord"):  # 직전 주문 잔량이 남았으면 새 주문도, 종료도 하지 않는다 (11/12 국내 ord 974 늦은 체결)
                left = rem_qty(nh.order_history(), st["last_ord"])
                if left != 0:
                    log("직전 주문 미체결: 대기", ord_no=st["last_ord"], rem=left, pos=pos)
                    time.sleep(LOOP_SEC)
                    continue
                st["last_ord"] = None
                keep()
            if not st["entered"] and (pos or filled_since(nh.order_history(), today, a.start)):
                st["entered"] = True
                keep()
            if pos and st["entry"] is None:
                st["entry"] = avg
                keep()
            if st["entered"] and pos == 0 and tgt != 0:
                log("잔고가 우리 청산 없이 0이 됨: 재진입하지 않고 종료", state=st)
                st["done"] = True
                keep()
                tgt = 0
            q = nh.price(ZN)
            last = float(q["occurs1_last_pric"])
            px = float(q["occurs1_bid_pric" if pos > 0 else "occurs1_ask_pric"]) if pos else last
            if pos and px > 0 and st["entry"] and not st["stopped"] and stop_hit(side, st["entry"], px, a.stop):
                st["stopped"] = True
                keep()
                log("손절", entry=st["entry"], px=px, ticks=round((px - st["entry"]) * side / TICK, 2))
                tgt = 0
            if STOP_FILE.exists() and tgt == 0 and not st["done"]:
                log("STOP 파일: 청산")
            pnl = round((last - st["entry"]) * pos / TICK * TICK_USD) if pos and st["entry"] else 0
            if time.time() - last_status > 60:
                log("상태", pos=pos, target=tgt, entry=st["entry"], last=last, pnl_usd_est=pnl)
                last_status = time.time()

            if pos == tgt:
                if tgt == 0 and (hm >= a.end or st["stopped"] or st["done"] or STOP_FILE.exists()):
                    st["done"] = True
                    keep()
                    return log("종료: 잔고 0", state=st)
                time.sleep(LOOP_SEC)
                continue

            diff = tgt - pos
            o_side = 1 if diff > 0 else -1
            log("주문", pos=pos, target=tgt, side=o_side, qty=abs(diff), dry=a.dry)
            if a.dry:
                time.sleep(LOOP_SEC)
                continue
            try:
                res = nh.order(o_side, qty=abs(diff), sym=ZN)
            except OrderUnknown as e:
                log("주문 응답 없음: 15초 뒤 잔고로 다시 판단", err=str(e))
                time.sleep(15)
                continue
            fill = nh.find_fill(res["ord_no"])
            log("체결", ord_no=res["ord_no"], fill=fill)
            st["last_ord"] = res["ord_no"]
            if tgt != 0:
                st["entered"] = True
                st["entry"] = None  # 다음 바퀴에 증권사 잔고 평균가로 채운다
            keep()
            for _ in range(15):  # 잔고 반영을 기다린다. 반영 전에 다시 돌면 같은 주문을 또 낸다
                if nh.position(ZN)[0] != pos:
                    break
                time.sleep(1)
            else:
                log("잔고 반영 15초 지연: 15초 더 기다린 뒤 다시 판단")
                time.sleep(15)
        except KeyboardInterrupt:
            return log("Ctrl+C: 루프 중단 (잔고는 그대로)")
        except Exception as e:  # noqa: BLE001 — 거절·끊김에도 멈추지 않는다
            log("오류: 5초 뒤 재시도", err=repr(e))
            time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
