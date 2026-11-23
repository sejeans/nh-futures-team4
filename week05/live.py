# 5주차 실전(모의): strategy.py 규칙을 하루 돌린다. 08:50 쯤 켜 두면
#   1) 어제 일봉(시가·종가)으로 방향을 정하고  2) 09:00 첫 시세에 시장가 진입  3) 1분마다 손절 확인  4) 15:30 시장가 청산
# 모든 시세·신호·주문은 results/live_YYYYMMDD.jsonl
#   python live.py --dry   주문 없이 신호와 가상 체결만 (지금 시세를 체결가로 본다)
#   python live.py --dry --side 1   드라이런에서 방향을 강제 (흐름 시험용)
#   python live.py         주문마다 y 확인
#   python live.py --yes   묻지 않음 (작업 스케줄러용)
# 잔고는 브로커 잔고가 기준이다. 시작할 때 잔고와 results/live_state.json 이 다르면 주문하지 않고 멈춘다
import json
import sys
import time
from datetime import datetime

import strategy as S
from fetch_data import KTB10, RESULTS, _nh

STATE = RESULTS / "live_state.json"
DRY, YES = "--dry" in sys.argv, "--yes" in sys.argv
ENTRY_LATEST = "09:15"   # 재시작 등으로 늦게 켜졌을 때 이 시각이 지나면 그날은 진입하지 않는다
EXIT_LATEST = "15:44"    # 청산 주문은 15:30 이 지나도 이 시각까지는 낸다 (보유를 다음 날로 넘기지 않기 위해)
FILL_TRIES = 60          # 주문내역 조회 1초 간격. 4주차 11/12 주문 974 는 접수까지 30초 (week04 7절)


def now_tm():
    return datetime.now().strftime("%H:%M:%S")


def journal(rec):
    rec = {"t": datetime.now().isoformat(timespec="seconds"), **rec}
    with open(RESULTS / f"live_{datetime.now():%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(_nh._mask(rec), ensure_ascii=False, default=str) + "\n")
    print(json.dumps(rec, ensure_ascii=False, default=str)[:300], flush=True)


def prev_bar(nh, today):
    """오늘보다 앞선 마지막 일봉 (12월물, 연결 아님). 08:45 이후엔 오늘 봉도 오므로 날짜로 거른다"""
    res = nh.call("/trade/v1/domestic/chart-daily", {
        "nght_tp": "1", "sym": KTB10, "inq_strt_dt": "00000000", "inq_ed_dt": "99999999", "req_qty": "10",
        "cidx_yn": "0", "nxt_key": "99999999", "fut_cidx_exp_mod": "0"})
    rows = sorted((o for o in res.get("Occurs1") or [] if o["occurs1_ref_dt"] < today),
                  key=lambda o: o["occurs1_ref_dt"])
    b = rows[-1]
    return {"day": b["occurs1_ref_dt"], "open": float(b["occurs1_open_pric"]), "close": float(b["occurs1_close_pric"])}


def quote(nh):
    p = nh.price(KTB10)
    return {"last": float(p["last_pric"]), "bid": float(p["bid_pric"]), "ask": float(p["ask_pric"])}


def open_qty(nh, ord_no):
    """주문내역의 미체결 잔량. 거부·취소·체결 완료면 0 (week04 live.py 와 같음)"""
    key = str(ord_no).strip().lstrip("0")
    for r in nh.order_history().get("Occurs1") or []:
        if r.get("occurs1_ord_no", "").strip().lstrip("0") == key:
            return 0 if (r.get("occurs1_ord_rejt_rsn") or "").strip() else int(float(r.get("occurs1_rem_ord_qty") or 0))
    return 0


def send(nh, qty_signed, why, q=None):
    """시장가 한 번. 체결가(모르면 None)와 성공 여부를 돌려준다. 응답이 없으면 잔고 변화로 판단"""
    side, qty = (1 if qty_signed > 0 else -1), abs(qty_signed)
    msg = f"{why}: {KTB10} 시장가 {'매수' if side > 0 else '매도'} {qty}"
    if DRY:
        px = q["ask"] if side > 0 else q["bid"]
        journal({"event": "주문(드라이런)", "msg": msg, "px": px})
        return px, True
    if not YES and input(f">>> {msg}. y: ").strip().lower() != "y":
        journal({"event": "주문 취소(사용자)", "msg": msg})
        return None, False
    before = nh.position(KTB10)[0]
    try:
        res = nh.order(side, qty=qty, sym=KTB10)
        fill = nh.find_fill(res["ord_no"], tries=FILL_TRIES)
        journal({"event": "주문", "msg": msg, "res": res, "fill": fill})
        if fill and not fill["reject"] and fill["qty"] >= qty:
            return fill["px"], True
        left = open_qty(nh, res["ord_no"])
        if left:
            journal({"event": "중단", "msg": f"{msg} 잔량 {left} 미체결. 주문내역·잔고를 직접 확인",
                     "pos": nh.position(KTB10)})
            sys.exit(1)
    except _nh.OrderUnknown as e:
        journal({"event": "주문 응답 없음", "msg": msg, "err": str(e)})
        time.sleep(3)
    except _nh.NHError as e:
        journal({"event": "주문 거부", "msg": msg, "err": str(e)})
        return None, False
    after, avg = nh.position(KTB10)
    journal({"event": "잔고로 확인", "before": before, "after": after, "avg": avg})
    ok = after - before == qty_signed
    return (avg if ok and after else None), ok


def close_out(nh, state, why, q):
    for attempt in range(3):
        px, ok = send(nh, -state["side"] * S.QTY, why, q)
        if ok:
            # 실제 체결가에 호가 넘기가 이미 들어 있으므로 수수료(추정)만 뺀다. 확정 손익은 예수금·체결내역으로 따로 확인
            pnl = None if px is None or state["entry_px"] is None else \
                round((state["side"] * (px - state["entry_px"]) - S.FEE_PT) * 1_000_000)
            journal({"event": "청산", "reason": why, "entry": state, "exit_px": px, "pnl_krw_after_fee_est": pnl})
            if not DRY:
                STATE.unlink(missing_ok=True)
            return True
        time.sleep(5)
        q = quote(nh)
    journal({"event": "중단", "msg": "청산 3회 실패. 잔고를 직접 확인", "pos": None if DRY else nh.position(KTB10)})
    sys.exit(1)


def main():
    nh = _nh.NH()
    today = datetime.now().strftime("%Y%m%d")
    bar = prev_bar(nh, today)
    prev_intra = round(bar["close"] - bar["open"], 4)
    sd = S.side(prev_intra)
    if DRY and "--side" in sys.argv:  # 드라이런 시험용: 신호와 상관없이 방향을 정해 진입·틱·청산 흐름을 돌려 본다
        sd = int(sys.argv[sys.argv.index("--side") + 1])
    state =json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
    pos = 0 if DRY else nh.position(KTB10)[0]
    expect = state["side"] * S.QTY if state else 0
    journal({"event": "시작", "dry": DRY, "prev_bar": bar, "prev_intra": prev_intra, "side": sd,
             "pred_pt": round(S.BETA * prev_intra, 4), "rule": {"BETA": S.BETA, "MIN_PREV": S.MIN_PREV,
             "STOP_PT": S.STOP_PT}, "state": state, "broker": pos})
    if pos != expect:
        journal({"event": "중단", "msg": f"잔고 {pos} ≠ 기록 {expect}. 직접 확인 후 live_state.json 을 고칠 것"})
        sys.exit(1)
    if state and state["day"] != today:  # 어제 청산하지 못한 보유. 바로 정리하고 오늘 신호는 따르지 않는다
        while now_tm() < S.ENTRY_TM + ":00":  # 모의 국내 운영 09:00~. 08:50 에 주문하면 3회 실패하고 끝난다
            time.sleep(5)
        close_out(nh, state, "전일 보유 정리", quote(nh))
        state, sd = None, 0

    while now_tm() < S.ENTRY_TM + ":00":
        time.sleep(5)

    while True:
        t = now_tm()
        try:
            q = quote(nh)
        except _nh.NHError as e:
            journal({"event": "시세 실패", "err": str(e)})
            time.sleep(20)
            continue
        if state is None:
            if sd and (t < ENTRY_LATEST + ":00" or DRY):  # 드라이런은 시험용이라 늦게 켜도 진입해 본다
                px, ok = send(nh, sd * S.QTY, "진입", q)
                if ok:
                    state = {"day": today, "side": sd, "entry_px": px, "entry_t": t, "prev_intra": prev_intra,
                             "stop_px": S.stop_price(sd, px) if px else None}
                    if not DRY:
                        STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                    journal({"event": "진입", "state": state, "q": q})
            if state is None:  # 신호 없음, 진입 시각 지남, 진입 실패 — 그날은 다시 시도하지 않는다
                journal({"event": "끝", "msg": "오늘 진입 없음", "side": sd, "q": q})
                return
            continue
        unreal = None if state["entry_px"] is None else round(state["side"] * (q["last"] - state["entry_px"]) * 1e6)
        journal({"event": "틱", "q": q, "side": state["side"], "entry_px": state["entry_px"], "unreal_krw": unreal})
        if state["entry_px"] is not None and S.stopped(state["side"], state["entry_px"], q["last"]):
            close_out(nh, state, "손절", q)
            break
        if t >= S.EXIT_TM + ":00":
            if t > EXIT_LATEST + ":00":
                journal({"event": "중단", "msg": "청산 시각을 지나 켜짐. 보유가 남아 있음, 직접 확인"})
                sys.exit(1)
            close_out(nh, state, "시간 청산", q)
            break
        time.sleep(60 - datetime.now().second % 60 + 1)  # 매분 1초
    journal({"event": "끝", "broker": None if DRY else nh.position(KTB10)})


if __name__ == "__main__":
    main()
