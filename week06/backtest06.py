# 6주차 백테스트: 같은 전략(2주차 볼린저)에 위험관리 규칙을 하나씩 더해 같은 기간, 같은 체결 가정으로 비교한다
#   python backtest06.py
# 체결 가정 (2주차 backtest.py 와 같음)
#   진입, 신호 청산: 5분봉 마감 시각의 1분봉 종가 ± 1틱 슬리피지. 수수료 1계약 왕복 2,400원
#   손절: 2주차는 1분봉 종가가 손절가를 넘었을 때 그 종가에 청산 (실전도 1분마다 확인)
#         6주차는 1분봉 고가, 저가가 손절가에 닿으면 손절가에 청산(봉 시가가 이미 넘었으면 시가). 실전은 10초마다 확인
# 결과: results/bt_summary.json, results/bt_trades.csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import risk as R
from data06 import RESULTS, load

sys.path.append(str(Path(__file__).resolve().parent.parent / "week02"))
from strategy import P, bollinger  # noqa: E402

SLIP = 1 * R.TICK
ENTRY_FROM, ENTRY_UNTIL = P["entry_window_close_time"]
WARMUP = P["bollinger"]["n"]      # 2주차 10/29 이후 규칙: 당일 봉 20개가 쌓인 뒤 진입
PERIODS = {"결정 9/11~10/30": ("2026-09-11", "2026-10-30"), "확인 11/02~11/20": ("2026-11-02", "2026-11-20")}

SCENARIOS = {  # 이름: Rules. 위에서 아래로 한 가지씩 더한다
    "0 위험관리 없음": R.Rules(stop=False, limit=None),
    "1 2주차 (손절 1분 종가, 한도 실현손실)": R.Rules(),
    "2 + 손절 즉시 판정": R.Rules(stop_touch=True),
    "3 + 한도 사전 확인": R.Rules(stop_touch=True, limit="worst"),
    "4 2계약 일괄 청산": R.Rules(stop_touch=True, limit="worst", lots=2),
    "5 2계약 분할 청산": R.Rules(stop_touch=True, limit="worst", lots=2, split=True),
}


def signals(b5):
    sig = bollinger(b5, warmup=WARMUP)
    n, k, dd = P["bollinger"]["n"], P["bollinger"]["k"], P["bollinger"]["std_ddof"]
    mid = b5.close.rolling(n).mean().values
    sd = b5.close.rolling(n).std(ddof=dd).values
    sig["far_long"] = b5.close.values >= mid + k * sd    # 매수 보유 중 반대편(상단) 밴드 도달
    sig["far_short"] = b5.close.values <= mid - k * sd
    return sig


def run(b1, sig, rules):
    entry = sig.entry[sig.entry != 0].to_dict()
    near = {1: set(sig.index[sig.exit_long]), -1: set(sig.index[sig.exit_short])}
    far = {1: set(sig.index[sig.far_long]), -1: set(sig.index[sig.far_short])}
    legs = []
    for day, g in b1[~b1.auction].groupby("day"):
        side, lots, stage, pnl = 0, 0, 0, 0.0
        for t, o, h, lo, c in zip(g.close_t, g.open, g.high, g.low, g.close):
            hm = t.strftime("%H:%M")
            if side:
                exits = []  # (계약 수, 청산가, 사유)
                sp = R.stop_price(side, e_px, stage)
                if hm >= R.EXIT_AT:
                    exits.append((lots, c, "15:25"))
                elif (rules.stop or stage) and rules.stop_touch and side * ((lo if side > 0 else h) - sp) <= 1e-9:
                    exits.append((lots, min(o, sp) if side > 0 else max(o, sp), "손절" if stage == 0 else "본전"))
                elif (rules.stop or stage) and not rules.stop_touch and R.stop_hit(side, e_px, stage, c):
                    exits.append((lots, c, "손절" if stage == 0 else "본전"))
                elif stage == 0 and t in near[side]:
                    n = lots // 2 if rules.split else lots
                    exits.append((n, c, "중심선"))
                elif stage == 1 and t in far[side]:
                    exits.append((lots, c, "반대 밴드"))
                for n, px, why in exits:
                    x_px = round(px - side * SLIP, 1)
                    krw = round(side * (x_px - e_px) * R.MULT * n - R.FEE_PER_LOT * n)
                    legs.append({"day": day, "trade": tid, "side": side, "lots": n, "entry_t": e_t, "entry_px": e_px,
                                 "exit_t": t, "exit_px": x_px, "reason": why, "krw": krw})
                    pnl += krw
                    lots -= n
                    if why == "중심선" and lots:
                        stage = 1
                if not lots:
                    side = 0
                continue  # 보유 중이거나 방금 청산한 봉에서는 진입하지 않는다 (2주차와 같음)
            sd = entry.get(t, 0)
            if sd and ENTRY_FROM <= hm < ENTRY_UNTIL and R.entry_allowed(rules, pnl):
                side, lots, stage = sd, rules.lots, 0
                e_t, e_px, tid = t, round(c + sd * SLIP, 1), f"{t:%m%d %H:%M}"
    return pd.DataFrame(legs)


def summary(legs, days):
    if legs.empty:
        return {"거래": 0, "손익": 0}
    tr = legs.groupby("trade").agg(krw=("krw", "sum"), day=("day", "first"))
    daily = tr.groupby("day").krw.sum().reindex(days, fill_value=0)
    eq = np.concatenate([[0], tr.krw.cumsum()])
    win, loss = tr.krw[tr.krw > 0], tr.krw[tr.krw <= 0]
    return {"거래": len(tr), "승률": round(len(win) / len(tr), 3), "손익": int(tr.krw.sum()),
            "평균이익": int(win.mean()) if len(win) else 0, "평균손실": int(loss.mean()) if len(loss) else 0,
            "최대낙폭": int((eq - np.maximum.accumulate(eq)).min()), "최악의 날": int(daily.min()),
            "한도 초과일": None, "청산": legs.groupby("reason").lots.sum().to_dict()}


def main():
    b1, b5 = load(1), load(5)
    sig = signals(b5)
    rows, all_legs = [], []
    for name, rules in SCENARIOS.items():
        legs = run(b1, sig, rules)
        legs.insert(0, "scenario", name)
        all_legs.append(legs)
        for per, (s, e) in PERIODS.items():
            days = pd.DatetimeIndex(sorted(b1.day[(b1.day >= s) & (b1.day <= e)].unique()))
            sub = legs[(legs.day >= s) & (legs.day <= e)]
            row = summary(sub, days)
            if len(sub):  # 하루 손실이 한도(계약 수 비례)를 넘은 날
                d = sub.groupby("day").krw.sum()
                row["한도 초과일"] = int((d < -R.LOSS_LIMIT_PER_LOT * rules.lots).sum())
            rows.append({"시나리오": name, "구간": per, **row})
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(res.drop(columns="청산").to_string(index=False))
    print(res[["시나리오", "구간", "청산"]].to_string(index=False))
    pd.concat(all_legs).to_csv(RESULTS / "bt_trades.csv", index=False, encoding="utf-8-sig")
    (RESULTS / "bt_summary.json").write_text(json.dumps(
        {"periods": PERIODS, "assumptions": {"slip_ticks": 1, "fee_per_lot": R.FEE_PER_LOT, "warmup": WARMUP},
         "rows": rows}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
