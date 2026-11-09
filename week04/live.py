# 4주차 실전(모의): strategy.py 규칙을 장중에 돌린다. 09:00 이후 켜 두면 1분마다 두 종목 시세 → 스프레드 → 손절 확인,
# 15:30 첫 틱에 z 를 계산해 진입·평균 복귀·시간 청산을 처리하고 끝낸다. 모든 틱과 주문은 results/live_YYYYMMDD.jsonl
#   python live.py --dry   주문 없이 신호만 (11/09 시험용)
#   python live.py         주문마다 y 확인
#   python live.py --yes   묻지 않음 (작업 스케줄러용)
# 두 다리 처리: 10년을 먼저 넣고 체결을 확인한 뒤 3년. 진입 중 3년이 실패하면 10년을 되돌린다.
# 청산 중 한쪽이 실패하면 그 다리만 2번 더 시도하고, 그래도 안 되면 멈추고 알린다 (잔고는 브로커 잔고가 기준)
import json
import sys
import time
from datetime import datetime

import pandas as pd

import strategy as S
from explore import YEARS, bars, implied_yield
from fetch_bars import KTB3, KTB10, RESULTS, _nh, fetch, load

STATE = RESULTS / "live_state.json"
DRY, YES = "--dry" in sys.argv, "--yes" in sys.argv
END_TM = "15:34"


def journal(rec):
    rec = {"t": datetime.now().isoformat(timespec="seconds"), **rec}
    with open(RESULTS / f"live_{datetime.now():%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(_nh._mask(rec), ensure_ascii=False, default=str) + "\n")
    print(json.dumps(rec, ensure_ascii=False, default=str)[:300])


def history(today):
    """지난 거래일별 SIGNAL_TM 스프레드. 저장된 분봉을 모으고, 15:30 봉까지 안 찬 날부터 어제까지 다시 받는다"""
    def merged(sym):
        d = pd.concat([load(p) for p in sorted(RESULTS.glob(f"bars_{sym}_1m_*.json"))])
        return d[~d.index.duplicated(keep="last")].sort_index()

    b = bars(merged(KTB3), merged(KTB10))
    last_tm = pd.Series(b.index, index=b.index).groupby(b.day).max().dt.strftime("%H:%M")
    done = last_tm[last_tm >= S.SIGNAL_TM].index
    start = (done.max() + pd.offsets.BDay(1)).strftime("%Y-%m-%d")
    yday = (pd.Timestamp(today) - pd.offsets.BDay(1)).strftime("%Y-%m-%d")
    if start <= yday:
        for sym in (KTB3, KTB10):
            fetch(sym, start, yday)
        b = bars(merged(KTB3), merged(KTB10))
    b = b[(~b.auction) & (b.day < pd.Timestamp(today))]
    sig = b[b.index.strftime("%H:%M") <= S.SIGNAL_TM].groupby("day").tail(1)
    full = sig.groupby("day").size().index  # 15:30 이전 봉이 있는 날
    return sig.set_index("day").spread_bp.loc[full]


def quote(nh):
    q = {}
    for sym in (KTB10, KTB3):
        p = nh.price(sym)
        q[sym] = {"last": float(p["last_pric"]), "bid": float(p["bid_pric"]), "ask": float(p["ask_pric"])}
    y = {s: implied_yield([q[s]["last"]], YEARS[s])[0] for s in q}
    return q, round((y[KTB10] - y[KTB3]) * 1e4, 3)


def broker_pos(nh):
    return {s: nh.position(s)[0] for s in (KTB3, KTB10)}


def target(side):
    return {KTB3: side * S.RATIO[0], KTB10: -side * S.RATIO[1]}


def send(nh, sym, qty_signed, why):
    """한 다리 주문. 체결되면 True. 응답이 없으면 잔고로 체결 여부를 본다"""
    if not qty_signed:
        return True
    side, qty = (1 if qty_signed > 0 else -1), abs(qty_signed)
    msg = f"{why}: {sym} 시장가 {'매수' if side > 0 else '매도'} {qty}"
    if DRY:
        journal({"event": "주문(드라이런)", "msg": msg})
        return True
    if not YES and input(f">>> {msg}. y: ").strip().lower() != "y":
        journal({"event": "주문 취소(사용자)", "msg": msg})
        return False
    before = nh.position(sym)[0]
    try:
        res = nh.order(side, qty=qty, sym=sym)
        fill = nh.find_fill(res["ord_no"])
        journal({"event": "주문", "msg": msg, "res": res, "fill": fill})
        if fill and not fill["reject"] and fill["qty"] >= qty:
            return True
    except _nh.OrderUnknown as e:
        journal({"event": "주문 응답 없음", "msg": msg, "err": str(e)})
        time.sleep(3)
    except _nh.NHError as e:
        journal({"event": "주문 거부", "msg": msg, "err": str(e)})
        return False
    after = nh.position(sym)[0]  # 체결을 못 찾았으면 잔고 변화로 판단
    journal({"event": "잔고로 확인", "sym": sym, "before": before, "after": after})
    return after - before == qty_signed


def move_to(nh, goal, why, rollback):
    """잔고를 goal 로 맞춘다. 10년 → 3년 순. rollback=True 면 두 번째 다리 실패 시 첫 다리를 되돌린다"""
    have = broker_pos(nh) if not DRY else {KTB3: 0, KTB10: 0}
    first = send(nh, KTB10, goal[KTB10] - have[KTB10], why)
    if not first:
        journal({"event": "첫 다리 실패", "why": why})
        return False
    for attempt in range(3):
        if send(nh, KTB3, goal[KTB3] - (broker_pos(nh)[KTB3] if not DRY else have[KTB3]), why):
            return True
        if rollback:
            break
        time.sleep(2)
    if rollback:
        ok = send(nh, KTB10, have[KTB10] - broker_pos(nh)[KTB10], why + " 되돌리기")
        journal({"event": "3년 실패 → 10년 되돌림", "ok": ok})
        return False
    journal({"event": "중단", "msg": "3년 다리를 못 맞춤. 잔고를 직접 확인", "pos": broker_pos(nh)})
    sys.exit(1)


def main():
    nh = _nh.NH()
    today = datetime.now().strftime("%Y-%m-%d")
    hist = history(today)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
    pos = broker_pos(nh)
    expect = target(state["side"]) if state else {KTB3: 0, KTB10: 0}
    journal({"event": "시작", "dry": DRY, "hist_days": len(hist), "hist_last": str(hist.index[-1].date()),
             "state": state, "broker": pos})
    if pos != expect and not DRY:
        journal({"event": "중단", "msg": f"잔고 {pos} ≠ 기록 {expect}. 직접 확인 후 live_state.json 을 고칠 것"})
        sys.exit(1)

    signaled = False
    while datetime.now().strftime("%H:%M") <= END_TM and not signaled:
        try:
            q, spread = quote(nh)
        except _nh.NHError as e:
            journal({"event": "시세 실패", "err": str(e)})
            time.sleep(30)
            continue
        now_tm = datetime.now().strftime("%H:%M")
        tick = {"event": "틱", "spread_bp": spread, "q": q, "side": state and state["side"]}
        if state and S.exit_reason(state["side"], float("nan"), spread, state["entry_spread"], 0) == "손절":
            if move_to(nh, {KTB3: 0, KTB10: 0}, "손절", rollback=False):
                journal({**tick, "event": "손절 청산", "entry": state})
                state = None
                STATE.unlink(missing_ok=True) if not DRY else None
            signaled = True  # 손절한 날은 다시 진입하지 않는다
        elif now_tm >= S.SIGNAL_TM:
            d = pd.concat([hist, pd.Series([spread], index=[pd.Timestamp(today)])])
            z = float(S.zscore(d).iloc[-1])
            held = int((hist.index > pd.Timestamp(state["entry_day"])).sum()) + 1 if state else 0
            journal({**tick, "event": "신호", "z": round(z, 3), "days_held": held,
                     "mean": round(float(hist.iloc[-S.N:].mean()), 3), "std": round(float(hist.iloc[-S.N:].std()), 3)})
            why = state and S.exit_reason(state["side"], z, spread, state["entry_spread"], held)
            if why:
                if move_to(nh, {KTB3: 0, KTB10: 0}, why, rollback=False):
                    journal({"event": "청산", "reason": why, "entry": state, "exit_spread": spread})
                    state = None
                    STATE.unlink(missing_ok=True) if not DRY else None
            elif not state and S.entry_side(z):
                side = S.entry_side(z)
                if move_to(nh, target(side), "진입", rollback=True):
                    state = {"side": side, "entry_day": today, "entry_spread": spread, "z": round(z, 3)}
                    if not DRY:
                        STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                    journal({"event": "진입", "state": state})
            signaled = True
        else:
            journal(tick)
        if not signaled:
            time.sleep(60)
    journal({"event": "끝", "state": state, "broker": broker_pos(nh)})


if __name__ == "__main__":
    main()
