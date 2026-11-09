# 해외 모의계좌 ZN 잔고를 시장가로 청산한다 (11/13 대회 전 계좌 비우기). 잔고를 읽고 반대 주문 1번.
# y 를 입력해야 주문한다. 거부·응답 없음이면 재주문하지 않고 멈춘다.
# 11/08(일) 17:15 장 닫힌 시간에 보낸 주문은 5016 「거래소주문전송중 오류발생」 거부, 대기 주문도 안 남음 → CME 개장(월 08:00) 후 실행
import json
import sys
from datetime import datetime

from nh_os import HERE, ZN, NHError, NHOverseas, OrderUnknown, _nh

RESULTS = HERE / "results"  # fetch_bars 에서 가져오면 nh_os 가 앞에 넣은 week02 것이 잡힌다


def main(sym=ZN):
    nh = NHOverseas()
    now = datetime.now()
    out = RESULTS / f"close_{sym}_{now:%Y%m%d_%H%M%S}.json"
    log = {"started": now.isoformat(timespec="seconds"), "sym": sym, "steps": []}

    def step(name, res):
        log["steps"].append({"name": name, "at": datetime.now().isoformat(timespec="milliseconds"), "res": _nh._mask(res)})
        out.write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[{name}] {json.dumps(_nh._mask(res), ensure_ascii=False, default=str)[:400]}")

    pos, avg = nh.position(sym)
    step("잔고", {"position": pos, "avg": avg})
    if not pos:
        return print("잔고 없음. 주문하지 않는다")
    q = nh.price(sym)
    step("직전 시세", {k: q[k] for k in ("occurs1_biz_dt", "occurs1_trd_tm", "occurs1_last_pric", "occurs1_bid_pric",
                                     "occurs1_ask_pric")})
    side = -1 if pos > 0 else 1
    if input(f"\n>>> {sym} 시장가 {'매수' if side > 0 else '매도'} {abs(pos)}계약으로 청산. y: ").strip().lower() != "y":
        sys.exit(f"중단. 기록: {out}")
    try:
        res = nh.order(side, qty=abs(pos), sym=sym)
        step("주문 응답", res)
    except OrderUnknown as e:
        step("응답 없음", {"err": str(e)})
        sys.exit("재주문하지 않는다. 주문내역·잔고로 체결 여부를 직접 확인")
    except NHError as e:
        step("거부", {"err": str(e)})
        sys.exit("거부됨")
    step("체결", nh.find_fill(res["ord_no"]) or {"msg": "주문내역에서 체결을 못 찾음"})
    step("주문 후 잔고", {"position": nh.position(sym)})
    print("기록:", out)


if __name__ == "__main__":
    main()
