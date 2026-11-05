# 11/02(월) 수동 점검: ZN 1계약 시장가 매수 → 체결·잔고 확인 → 매도 청산 → 슬리피지·수수료 실측
# 2주차 manual_roundtrip.py 와 같은 순서. 주문 전마다 y 를 입력해야 진행한다. 모의계좌 전용 (nh.py 가 실주문 차단)
# 판정 (11/02 주문 전에 정함, precheck.py): 왕복 비용(직전 체결가 대비 슬리피지 + 수수료) ≤ 1.5틱 이면 발표 전후 전략 통과
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from nh_os import SPEC, ZN, NHError, NHOverseas, OrderUnknown, _nh

OUT = Path(__file__).resolve().parent / "results" / f"manual_roundtrip_{datetime.now():%Y%m%d_%H%M%S}.json"
TICK, TICK_USD = SPEC["ZN"]["tick"], SPEC["ZN"]["tick_usd"]
PASS_TICKS = 1.5


def main():
    nh = NHOverseas()
    today = f"{datetime.now():%Y%m%d}"
    log = {"started": datetime.now().isoformat(timespec="seconds"), "sym": ZN, "steps": []}

    def step(name, res):
        log["steps"].append({"name": name, "at": datetime.now().isoformat(timespec="milliseconds"), "res": _nh._mask(res)})
        OUT.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[{name}]\n{json.dumps(_nh._mask(res), ensure_ascii=False)[:600]}")

    def ask(msg):
        if input(f"\n>>> {msg} 진행하려면 y: ").strip().lower() != "y":
            sys.exit(f"중단. 기록: {OUT}")

    step("시작 잔고", nh.open_interest())
    if nh.position()[0]:
        sys.exit("이미 ZN 잔고가 있다. 비우고 시작한다")
    step("예수금(전)", nh.deposit(biz_dt=today))
    step("누적손익(전)", nh.cumulative_pl(today, today))

    legs = []
    for side, name in [(1, "매수"), (-1, "매도 청산")]:
        ask(f"{ZN} 시장가 {name} 1계약")
        q = nh.price(ZN)
        step(f"{name} 직전 현재가", q)
        res = {}
        try:
            res = nh.order(side)
            step(f"{name} 주문 응답", res)
        except OrderUnknown as e:
            step(f"{name} 응답 없음", {"err": str(e)})
            print("재주문하지 않는다. 아래 주문내역·잔고로 체결 여부를 본다")
        except NHError as e:
            step(f"{name} 거부", {"err": str(e)})
            sys.exit("거부됨" + ("  ※ 매수는 체결된 상태 — 잔고를 직접 확인하고 청산할 것" if side < 0 else ""))
        time.sleep(1)
        fill = nh.find_fill(res["ord_no"]) if res.get("ord_no") else None
        step(f"{name} 체결", fill or {"msg": "주문내역에서 체결을 못 찾음"})
        step(f"{name} 후 잔고", nh.open_interest())
        print("→ 순포지션·평균가", nh.position())
        if fill and fill["px"]:
            last, bid, ask_ = (float(q[f"occurs1_{k}_pric"]) for k in ("last", "bid", "ask"))
            legs.append({"side": side, "fill": fill["px"], "last": last, "bid": bid, "ask": ask_,
                         "slip_vs_last_ticks": round((fill["px"] - last) * side / TICK, 2),
                         "slip_vs_quote_ticks": round((fill["px"] - (ask_ if side > 0 else bid)) * side / TICK, 2)})

    time.sleep(2)
    step("예수금(후)", nh.deposit(biz_dt=today))
    pl = nh.cumulative_pl(today, today)
    step("누적손익(후)", pl)
    fee = sum(float(r.get("occurs1_fee") or 0) for r in pl if r.get("occurs1_prd_cd", "").strip().startswith("ZN"))
    slip = sum(x["slip_vs_last_ticks"] for x in legs) if len(legs) == 2 else None
    cost = None if slip is None else slip + fee / TICK_USD
    log["result"] = {"legs": legs, "fee_usd_roundtrip": fee, "slip_vs_last_ticks_roundtrip": slip,
                     "cost_ticks_roundtrip": cost, "pass_ticks": PASS_TICKS,
                     "pass": None if cost is None else cost <= PASS_TICKS,
                     "pnl_usd": round((legs[1]["fill"] - legs[0]["fill"]) / TICK * TICK_USD, 2) if len(legs) == 2 else None}
    step("결과", log["result"])
    print(f"""
확인할 것
  1. 매수 후 잔고 trd_tp 가 '1', 매도 후 ZN 잔고 0건인가
  2. 체결가가 주문내역(ord_avg_pric 또는 exec_pric)에 나오는가
  3. 수수료가 누적손익(fee)에 잡히는가 — 0 이면 예수금·주문내역에서 다시 찾는다
  4. 왕복 비용 {cost} 틱 (기준 {PASS_TICKS}틱) → {log['result']['pass']}
※ 1회 측정이라 슬리피지는 운이 섞인다. 판정은 이 값으로 하되 README 에 1회 측정임을 적는다
기록: {OUT}""")


if __name__ == "__main__":
    main()
