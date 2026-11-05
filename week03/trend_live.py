# 3주차 실전(모의): 추세추종 TSMOM 12개월 — 직전 완성 일봉 종가가 252거래일 전보다 높으면 매수 1, 낮으면 매도 1
# 하루 1번 실행한다 (모의 운영 07:00~24:00). 신호를 계산하고, 목표 포지션과 지금 잔고가 다르면 차이만큼 시장가 주문.
# 주문 전에 y 를 입력해야 진행한다. --yes 면 묻지 않는다 (작업 스케줄러용, run_trend.bat).
# 모의계좌 전용 (nh.py 가 실주문 차단). 신호 계산은 strategies.py 와 같은 함수.
import json
import sys
from datetime import datetime

from strategies import LIVE, adjust, daily, roll_days, tsmom  # 먼저: nh_os 가 week02 를 sys.path 앞에 넣는다
from fetch_bars import RESULTS, save
from nh_os import SPEC, ZN, NHError, NHOverseas, OrderUnknown, _nh

QTY = 1
ROLL_BY = "2026-11-25"  # ZNZ26 잔고 만기 11/30 [추정: 실물인수도 통지일 전]. 이날부터는 멈추고 3월물로 직접 교체한다


def main():
    now = datetime.now()
    if f"{now:%Y-%m-%d}" >= ROLL_BY:
        sys.exit(f"{ROLL_BY} 이후: {ZN} 만기 전 교체 시점. 자동 주문하지 않는다 — 3월물로 바꾸고 ROLL_BY 를 고칠 것")
    nh = NHOverseas()
    out = RESULTS / f"trend_live_{now:%Y%m%d_%H%M%S}.json"
    log = {"started": now.isoformat(timespec="seconds"), "rule": LIVE, "sym": ZN, "steps": []}

    def step(name, res):
        log["steps"].append({"name": name, "at": datetime.now().isoformat(timespec="milliseconds"), "res": _nh._mask(res)})
        out.write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[{name}] {json.dumps(_nh._mask(res), ensure_ascii=False, default=str)[:400]}")

    path = save(f"bars_ZN_cont_1d_{now:%Y%m%d_%H%M}.json", nh.chart_daily(ZN, cidx="1"))
    d = daily("ZN", path, until=f"{now:%Y-%m-%d}")  # 오늘 날짜 봉은 진행 중이라 뺀다
    c = adjust(d, roll_days(d, SPEC["ZN"]["tick"])).close
    target = int(tsmom(c).iloc[-1]) * QTY
    step("신호", {"last_bar": f"{c.index[-1]:%Y-%m-%d}", "close_adj": c.iloc[-1],
                "close_252_ago": c.iloc[-253], "date_252_ago": f"{c.index[-253]:%Y-%m-%d}", "target": target})

    pos, avg = nh.position(ZN)
    step("잔고", {"position": pos, "avg": avg})
    diff = target - pos
    if abs(diff) > 2 * QTY:  # 뒤집기(+1 → -1)가 최대. 그보다 크면 잔고가 예상과 다르다
        step("중단", {"msg": f"주문 수량 {diff} 이 {2 * QTY} 을 넘는다. 잔고를 직접 확인"})
        sys.exit(1)
    if not diff:
        step("결과", {"msg": "목표 = 잔고. 주문 없음"})
        return
    q = nh.price(ZN)
    step("직전 현재가", q)
    if "--yes" not in sys.argv and input(f"\n>>> {ZN} 시장가 {'매수' if diff > 0 else '매도'} {abs(diff)}계약 (잔고 {pos} → 목표 {target}). y: ").strip().lower() != "y":
        sys.exit(f"중단. 기록: {out}")
    try:
        res = nh.order(1 if diff > 0 else -1, qty=abs(diff))
        step("주문 응답", res)
    except OrderUnknown as e:
        step("응답 없음", {"err": str(e)})
        sys.exit("재주문하지 않는다. 주문내역·잔고로 체결 여부를 직접 확인")
    except NHError as e:
        step("거부", {"err": str(e)})
        sys.exit("거부됨")
    fill = nh.find_fill(res["ord_no"])
    step("체결", fill or {"msg": "주문내역에서 체결을 못 찾음"})
    step("주문 후 잔고", {"position": nh.position(ZN)})
    print("기록:", out)


if __name__ == "__main__":
    main()
