# 5주차 백테스트 — strategy.py 규칙을 일봉(2022~2026)과 1분봉(9/11~, 실전과 같은 09:00 진입·15:30 청산)으로 돌린다
#   python backtest.py --stops   손절 폭 후보를 학습·검증 구간(2022~2024)에서만 비교 (시험 구간은 출력하지 않는다)
#   python backtest.py           확정한 규칙으로 전 구간. results/backtest_summary.json, backtest_trades.csv
# 체결 가정
#   일봉: 시가(08:45) 진입, 종가(15:45) 청산. 손절은 고가·저가가 손절가에 닿으면 손절가에서 1틱 불리하게 청산
#         (하루 안에서 고가·저가가 먼저 왔는지 모르므로, 닿은 날은 무조건 손절로 본다 = 보수적)
#   1분봉: 09:00 봉 시가 진입, 15:30 봉 시가 청산 (live.py 와 같은 시각). 손절은 1분봉 종가로 판정, 다음 봉 시가에 청산
#   비용: 왕복 COST_PT (호가 넘기 1틱 + 수수료) 를 거래마다 뺀다
import json
import sys

import numpy as np
import pandas as pd

import strategy as S
from analysis import build
from fetch_data import RESULTS, load_daily, load_minute

KRW = 1_000_000  # 1포인트 = 1,000,000원 (승수)
TICK = 0.01


def daily_trades(d, stop):
    t = d[["open", "high", "low", "close", "prev_intra", "split"]].copy()
    t["side"] = [S.side(x) for x in t.prev_intra]
    t = t[t.side != 0].copy()
    t["entry"] = t.open
    t["exit"] = t.close
    t["stopped"] = False
    if stop is not None:
        long_hit = (t.side > 0) & (t.low <= t.entry - stop)
        short_hit = (t.side < 0) & (t.high >= t.entry + stop)
        hit = long_hit | short_hit
        t.loc[hit, "exit"] = t.entry[hit] - t.side[hit] * (stop + TICK)
        t.loc[hit, "stopped"] = True
    t["pnl_pt"] = t.side * (t.exit - t.entry) - S.COST_PT
    t["pnl_krw"] = (t.pnl_pt * KRW).round()
    return t


def stats(t, days):
    """t: 거래 표, days: 그 구간 거래일 수 (거래 안 한 날 = 0원)"""
    if not len(t):
        return {"trades": 0}
    daily = t.pnl_krw.reindex(days, fill_value=0.0)
    eq = daily.cumsum()
    return {"days": len(days), "trades": len(t), "long": int((t.side > 0).sum()), "short": int((t.side < 0).sum()),
            "hit": round(float((t.pnl_pt > 0).mean()), 3), "total_krw": int(t.pnl_krw.sum()),
            "per_trade_krw": int(t.pnl_krw.mean()), "stopped": int(t.stopped.sum()),
            "sharpe_annual": round(float(daily.mean() / daily.std() * np.sqrt(250)), 2) if daily.std() else None,
            "max_drawdown_krw": int((eq - eq.cummax()).min())}


def baselines(d):
    """비교 기준: 매일 장중 매수 / 전일 방향 따라가기(반전의 반대) — 같은 비용"""
    out = {}
    for name, sd in (("매일 매수", pd.Series(1, index=d.index)),
                     ("전일 방향 추종(같은 기준)", -pd.Series([S.side(x) for x in d.prev_intra], index=d.index))):
        t = d.assign(side=sd)
        t = t[t.side != 0]
        pnl = (t.side * t.intra - S.COST_PT) * KRW
        out[name] = {"trades": len(t), "total_krw": int(pnl.sum()), "hit": round(float((pnl > 0).mean()), 3)}
    return out


def minute_check():
    """1분봉이 있는 날(9/11~): 실전과 같은 09:00 진입 · 15:30 청산 vs 일봉 시가·종가. 신호는 일봉의 전일 장중으로 같다"""
    m = load_minute("ktb")
    k = load_daily("ktb")
    k["prev_intra"] = (k.close - k.open).shift()
    rows = []
    for day, g in m.groupby(m.index.normalize()):
        if day not in k.index:
            continue
        sd = S.side(k.prev_intra[day])
        e = g[g.index.strftime("%H:%M") >= S.ENTRY_TM]
        x = g[g.index.strftime("%H:%M") >= S.EXIT_TM]
        if not sd or e.empty or x.empty:
            continue
        entry, exit_, stopped = e.open.iloc[0], x.open.iloc[0], False
        path = e[e.index < x.index[0]]
        if S.STOP_PT is not None:
            sp = S.stop_price(sd, entry)
            hit = path[sd * (path.close - sp) <= 0]
            if len(hit):
                nxt = path[path.index > hit.index[0]]
                exit_ = nxt.open.iloc[0] if len(nxt) else x.open.iloc[0]
                stopped = True
        rows.append({"day": day.date(), "side": sd, "prev_intra": round(k.prev_intra[day], 2),
                     "live_entry": entry, "live_exit": exit_, "stopped": stopped,
                     "live_krw": round((sd * (exit_ - entry) - S.COST_PT) * KRW),
                     "daily_krw": round((sd * (k.close[day] - k.open[day]) - S.COST_PT) * KRW)})
    r = pd.DataFrame(rows)
    return r, {"days": len(r), "live_total_krw": int(r.live_krw.sum()), "daily_total_krw": int(r.daily_krw.sum()),
               "same_sign_days": int((np.sign(r.live_krw) == np.sign(r.daily_krw)).sum()),
               "corr": round(float(r.live_krw.corr(r.daily_krw)), 3)}


def main():
    d = build()
    d = d[d.prev_intra.notna()]
    if "--stops" in sys.argv:
        tv = d[d.split != "test"]
        for stop in (None, 0.2, 0.3, 0.4, 0.5):
            t = daily_trades(tv, stop)
            print(f"손절 {stop}:", {sp: stats(t[t.split == sp], tv[tv.split == sp].index) for sp in ("fit", "val")})
        return
    t = daily_trades(d, S.STOP_PT)
    out = {"rule": {"BETA": S.BETA, "MIN_PREV": S.MIN_PREV, "STOP_PT": S.STOP_PT, "COST_PT": S.COST_PT},
           "by_split": {sp: stats(t[t.split == sp], d[d.split == sp].index) for sp in ("fit", "val", "test")},
           "test_by_year": {int(y): stats(g, d[(d.split == "test") & (d.index.year == y)].index)
                            for y, g in t[t.split == "test"].groupby(t[t.split == "test"].index.year)},
           "baselines_test": baselines(d[d.split == "test"])}
    mr, out["minute_window"] = minute_check()
    (RESULTS / "backtest_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                   encoding="utf-8")
    t.to_csv(RESULTS / "backtest_trades.csv", float_format="%.6g", encoding="utf-8-sig")
    mr.to_csv(RESULTS / "backtest_minute_window.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
