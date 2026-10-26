# 10/26(월) 장중 수동 점검: 1계약 매수 → 체결·잔고 확인 → 매도 청산 → 수수료 실측
# 주문 전마다 y 를 입력해야 진행한다. 모의계좌 전용 (nh.py 가 실주문 차단)
#   python manual_roundtrip.py      체결조건 FAK
#   python manual_roundtrip.py 1    FAK 가 거부되면 FAS 로 다시
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from nh import NH, NHError, OrderUnknown, SYM, _mask
from strategy import MULT

OUT = Path(__file__).resolve().parent / "results" / f"manual_roundtrip_{datetime.now():%Y%m%d_%H%M%S}.json"


def main():
    exec_cnd = sys.argv[1] if len(sys.argv) > 1 else "3"
    nh = NH()
    log = {"started": datetime.now().isoformat(timespec="seconds"), "sym": SYM, "exec_cnd": exec_cnd, "steps": []}

    def step(name, res):
        log["steps"].append({"name": name, "at": datetime.now().isoformat(timespec="seconds"), "res": _mask(res)})
        OUT.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[{name}]\n{json.dumps(_mask(res), ensure_ascii=False)[:800]}")

    def ask(msg):
        if input(f"\n>>> {msg} 진행하려면 y: ").strip().lower() != "y":
            sys.exit(f"중단. 기록: {OUT}")

    oi = nh.open_interest()
    step("시작 잔고", oi)
    if oi.get("Occurs1"):
        sys.exit("이미 잔고가 있다. 비우고 시작한다")
    d0 = nh.deposit()
    step("예수금(전)", d0)

    fills = []
    for side, name in [(1, "매수"), (-1, "매도 청산")]:
        step(f"{name} 전 호가", nh.price_bid())
        ask(f"{SYM} 시장가 {name} 1계약 (체결조건 {exec_cnd})")
        res = {}
        try:
            res = nh.order(side, exec_cnd=exec_cnd)
            step(f"{name} 주문 응답", res)
        except OrderUnknown as e:
            step(f"{name} 응답 없음", {"err": str(e)})
            print("재주문하지 않는다. 아래 주문내역·잔고로 체결 여부를 본다")
        except NHError as e:
            step(f"{name} 거부", {"err": str(e)})
            sys.exit("거부됨. FAK 문제면: python manual_roundtrip.py 1"
                     + ("  ※ 매수는 체결된 상태 — 잔고를 직접 확인하고 청산할 것" if side < 0 else ""))
        time.sleep(1)
        fill = nh.find_fill(res["ord_no"]) if res.get("ord_no") else None
        step(f"{name} 체결", fill or {"msg": "주문내역에서 체결을 못 찾음"})
        step(f"{name} 후 주문내역", nh.order_history())
        oi = nh.open_interest()
        step(f"{name} 후 잔고", oi)
        rows = oi.get("Occurs1") or []
        print(f"→ 잔고 {len(rows)}건", [(r.get("occurs1_trd_div"), r.get("occurs1_opint_qty"), r.get("occurs1_avg_pric")) for r in rows])
        if fill and fill["px"]:
            fills.append(fill["px"])

    time.sleep(2)
    d1 = nh.deposit()
    step("예수금(후)", d1)
    fee = float(d1.get("fee") or 0) - float(d0.get("fee") or 0)
    log["result"] = {
        "fills": fills,
        "fee_krw": fee,
        "fee_rate": fee / (sum(fills) * MULT) if fills else None,
        "pnl_krw": round((fills[1] - fills[0]) * MULT) if len(fills) == 2 else None,
    }
    step("결과", log["result"])
    print(f"""
확인할 것 (trade.py 가 기대는 가정)
  1. 매수 후 잔고의 trd_div 가 '1' 인가          → 아니면 nh.py BAL_SIDE 수정
  2. 매도 후 잔고가 0건인가 (반대 포지션이 안 생겼나)
  3. 체결가가 주문내역(avg_exec_pric)에 나오는가
  4. 수수료 {fee:,.0f}원 → trade.py FEE_KRW = 주문 1회당 {fee / 2:,.0f}원
기록: {OUT}""")


if __name__ == "__main__":
    main()
