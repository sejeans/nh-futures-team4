# 11/09(월) 장중 수동 점검: 3년 3 : 10년 1 스프레드를 진입했다가 바로 청산해서 수수료·체결가·두 다리 시차를 잰다
# 진입 = 10년 매도 1 → 3년 매수 3 (스티프닝 방향, 비용 측정이 목적이라 방향은 상관없음), 청산 = 10년 매수 1 → 3년 매도 3
# 거래량이 적은 10년을 먼저 넣는다. 주문 전마다 y 확인 (--yes 면 묻지 않음). 모의계좌 전용 (nh.py 가 실주문 차단)
# week02/manual_roundtrip.py 를 두 다리용으로 고친 것
import json
import sys
import time
from datetime import datetime

from fetch_bars import KTB3, KTB10, RESULTS, _nh
from explore import MULT

OUT = RESULTS / f"manual_roundtrip_{datetime.now():%Y%m%d_%H%M%S}.json"
LEGS_OPEN = [(KTB10, -1, 1), (KTB3, +1, 3)]
LEGS_CLOSE = [(KTB10, +1, 1), (KTB3, -1, 3)]


def main():
    nh = _nh.NH()
    log = {"started": datetime.now().isoformat(timespec="seconds"), "steps": []}

    def step(name, res):
        log["steps"].append({"name": name, "at": datetime.now().isoformat(timespec="milliseconds"), "res": _nh._mask(res)})
        OUT.write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[{name}] {json.dumps(_nh._mask(res), ensure_ascii=False, default=str)[:300]}")

    def ask(msg):
        if "--yes" not in sys.argv and input(f"\n>>> {msg} 진행하려면 y: ").strip().lower() != "y":
            sys.exit(f"중단. 기록: {OUT}")

    if nh.open_interest().get("Occurs1"):
        sys.exit("이미 잔고가 있다. 비우고 시작한다")
    fee0 = float(nh.deposit().get("fee") or 0)
    fills = []
    for phase, legs in (("진입", LEGS_OPEN), ("청산", LEGS_CLOSE)):
        for sym, side, qty in legs:
            b = nh.price_bid(sym)["Occurs1"][0]
            quote = {"bid": float(b["occurs1_bid_best_pric"]), "ask": float(b["occurs1_ask_best_pric"])}
            step(f"{phase} {sym} 호가", quote)
            ask(f"{phase}: {sym} 시장가 {'매수' if side > 0 else '매도'} {qty}계약 (FAS)")
            t0 = time.monotonic()
            try:
                res = nh.order(side, qty=qty, sym=sym)
                step(f"{phase} {sym} 주문 응답", res)
            except (_nh.OrderUnknown, _nh.NHError) as e:
                step(f"{phase} {sym} 실패", {"err": str(e), "position": {s: nh.position(s) for s in (KTB3, KTB10)}})
                sys.exit("멈춤. 재주문하지 않는다 — 잔고를 보고 남은 다리를 직접 정리할 것")
            fill = nh.find_fill(res["ord_no"])
            step(f"{phase} {sym} 체결", {**(fill or {"msg": "체결 못 찾음"}), "order_to_fill_s": round(time.monotonic() - t0, 2)})
            if fill and fill["px"]:
                fills.append({"phase": phase, "sym": sym, "side": side, "qty": qty, "px": fill["px"], **quote,
                              "slip_ticks": round((fill["px"] - (quote["ask"] if side > 0 else quote["bid"])) * side / 0.01, 2)})
        step(f"{phase} 후 잔고", {s: nh.position(s) for s in (KTB3, KTB10)})

    time.sleep(2)
    fee = float(nh.deposit().get("fee") or 0) - fee0
    notional = sum(f["px"] * f["qty"] * MULT for f in fills)
    pnl = sum(-f["side"] * f["px"] * f["qty"] * MULT for f in fills)
    log["result"] = {"fills": fills, "fee_krw": fee, "notional_krw": notional,
                     "fee_rate_per_side": fee / notional if notional else None, "pnl_before_fee_krw": round(pnl)}
    step("결과", log["result"])
    print("기록:", OUT)


if __name__ == "__main__":
    main()
