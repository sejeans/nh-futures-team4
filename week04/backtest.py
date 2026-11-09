# 4주차 백테스트: strategy.py 규칙을 1분봉(9/11~)에 적용한다
# 신호·진입·평균 복귀·시간 청산은 매일 SIGNAL_TM 봉에서, 손절은 매 1분봉에서 본다. 체결은 그 봉 종가 + 실측 왕복 비용
# 두 다리가 같은 분에 체결된 봉만 쓴다 (explore.bars 의 inner join)
import json
import sys

import pandas as pd

import strategy as S
from explore import MULT, RESULTS, bars


def run(b):
    b = b[~b.auction]
    sig = b[b.index.strftime("%H:%M") <= S.SIGNAL_TM].groupby("day").tail(1)  # 날마다 15:30 이전 마지막 봉
    z = S.zscore(sig.set_index("day").spread_bp)
    sig_at = dict(zip(sig.day, sig.index))
    trades, pos = [], None
    days = list(z.index)
    for i, day in enumerate(days):
        today = b[b.day == day]
        if pos:  # 손절은 장중 매 분
            for t, r in today[today.index < sig_at[day]].iterrows():
                if S.exit_reason(pos["side"], float("nan"), r.spread_bp, pos["entry_spread"], 0) == "손절":
                    pos.update(exit_t=t, exit_spread=r.spread_bp, exit3=r.close3, exit10=r.close10, reason="손절")
                    break
        r = today.loc[sig_at[day]]
        if pos and "reason" not in pos:
            why = S.exit_reason(pos["side"], z[day], r.spread_bp, pos["entry_spread"], i - pos["i"])
            if why:
                pos.update(exit_t=sig_at[day], exit_spread=r.spread_bp, exit3=r.close3, exit10=r.close10, reason=why)
        if pos and "reason" in pos:
            trades.append(pos)
            stopped_today, pos = True, None
        else:
            stopped_today = False
        if not pos and not stopped_today:  # 청산한 날은 다시 진입하지 않는다
            side = S.entry_side(z[day])
            if side:
                pos = {"side": side, "i": i, "entry_t": sig_at[day], "z": round(float(z[day]), 2),
                       "entry_spread": r.spread_bp, "entry3": r.close3, "entry10": r.close10}
    open_pos = pos
    for t in trades:
        n3, n10 = S.RATIO
        t["pnl_krw"] = round(t["side"] * (n3 * (t["exit3"] - t["entry3"]) - n10 * (t["exit10"] - t["entry10"])) * MULT)
        t["net_krw"] = t["pnl_krw"] - S.COST_KRW
        t["spread_chg_bp"] = round(t["side"] * (t["exit_spread"] - t["entry_spread"]), 2)
    return trades, open_pos, z


def main(path3, path10):
    S.selfcheck()
    trades, open_pos, z = run(bars(path3, path10))
    df = pd.DataFrame(trades)
    summary = {"rule": {"N": S.N, "K": S.K, "STOP_BP": S.STOP_BP, "MAX_DAYS": S.MAX_DAYS, "SIGNAL_TM": S.SIGNAL_TM,
                        "RATIO": S.RATIO, "COST_KRW": S.COST_KRW},
               "z_days": int(z.notna().sum()), "trades": len(df),
               "net_krw": int(df.net_krw.sum()) if len(df) else 0,
               "gross_krw": int(df.pnl_krw.sum()) if len(df) else 0,
               "wins": int((df.net_krw > 0).sum()) if len(df) else 0,
               "open_position": {k: (str(v) if k.endswith("_t") else v) for k, v in open_pos.items()} if open_pos else None,
               "z_last": round(float(z.iloc[-1]), 2)}
    if len(df):
        df.to_csv(RESULTS / "backtest_trades.csv", index=False)
        cols = ["side", "z", "entry_t", "entry_spread", "exit_t", "exit_spread", "reason", "spread_chg_bp", "pnl_krw", "net_krw"]
        print(df[cols].round(2).to_string(index=False))
    (RESULTS / "backtest_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:3])
