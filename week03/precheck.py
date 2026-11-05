# 손익을 보기 전 점검: 발표 전후(ZN)와 커브 스프레드(ZF/ZN)의 움직임 크기 vs 비용
# 방향은 보지 않고 크기만 본다. 기준은 backtest.py 의 MAX_COST_SHARE (비용 ≤ 움직임 중앙값의 20%)
import json

import numpy as np
import pandas as pd

from backtest import COST_TICKS, MAX_COST_SHARE, N, K, PERIODS, SLIP_TICKS, bars
from fetch_bars import RESULTS, load
from nh_os import SPEC

ET = "America/New_York"
# 시간은 미국 동부 기준. 지표 발표 8:30 ET (11/1 이전 한국 21:30, 이후 22:30), CME 정규장 8:20 ET 개장
RANGE_FROM, RANGE_UNTIL, EXIT_AT = "08:20", "08:35", "09:50"  # 9:50 ET = 이번 주 한국 23:50 (모의 운영 24:00 전 청산)
FYT = {"ZF": 3, "ZN": -2}  # CME 5년·10년 스프레드 기준 비율 (CME yield-curve-spread-trades.pdf)


def et(b):
    b = b.copy()
    b.index = b.index.tz_localize("Asia/Seoul").tz_convert(ET)
    return b


def event(b, tick):
    """거래일별 8:20~8:35 ET 범위 폭, 8:35 → 9:50 종가 변화 크기 (틱)"""
    rows = []
    for d, g in b.groupby(b.index.date):
        hm = g.index.strftime("%H:%M")
        rng, at = g[(hm >= RANGE_FROM) & (hm < RANGE_UNTIL)], g[hm == RANGE_UNTIL]
        end = g[hm < EXIT_AT]
        if len(rng) < 3 or at.empty or end.empty:
            continue
        rows.append({"day": d, "range": (rng.high.max() - rng.low.min()) / tick,
                     "move": abs(end.close.iloc[-1] - at.open.iloc[0]) / tick})
    return pd.DataFrame(rows)


def main():
    b5 = {k: et(bars(load(RESULTS / f"bars_{k}Z26_1m_20260824_20261030.json"), 5)) if k == "ZN"
          else et(load(RESULTS / f"bars_{k}Z26_5m_20261101.json")) for k in ("ZN", "ZF")}
    sel = slice(PERIODS["선택"][0], PERIODS["선택"][1] + " 23:59")
    out = {}

    # 1) 발표 전후: ZN 단일 종목
    t = SPEC["ZN"]["tick"]
    ev = event(b5["ZN"][sel], t)
    ev = ev[pd.to_datetime(ev.day).dt.dayofweek < 5]
    out["event_ZN"] = {"days": len(ev), "range_median_ticks": round(ev.range.median(), 2),
                       "move_median_ticks": round(ev.move.median(), 2),
                       "cost_share_vs_move": round(COST_TICKS / ev.move.median(), 3)}

    # 2) 커브 스프레드 패키지 (+3 ZF −2 ZN), USD
    px = pd.DataFrame({k: b5[k].close for k in b5}).dropna()[sel]
    usd = sum(n * px[k] / SPEC[k]["tick"] * SPEC[k]["tick_usd"] for k, n in FYT.items())
    cost_usd = 2 * SLIP_TICKS * sum(abs(n) * SPEC[k]["tick_usd"] for k, n in FYT.items())  # 5계약 왕복 1틱씩
    beta = np.polyfit(px.ZF.diff().dropna(), px.ZN.diff().dropna(), 1)[0]  # ZN 가격 변화 / ZF 가격 변화
    mid, sd = usd.rolling(N).mean(), usd.rolling(N).std(ddof=0)
    pu, lo, up = usd.shift(), mid - K * sd, mid + K * sd
    sig = ((pu < lo.shift()) & (usd >= lo)) | ((pu > up.shift()) & (usd <= up))
    dist = (mid - usd).abs()[sig]
    out["curve_FYT"] = {"ratio": FYT, "beta_dZN_dZF": round(beta, 3), "cost_usd_roundtrip": cost_usd,
                        "signals_per_day": round(sig.sum() / px.index.normalize().nunique(), 2),
                        "dist_to_mid_median_usd": round(dist.median(), 2),
                        "cost_share": round(cost_usd / dist.median(), 3)}
    # 3) 발표 전후의 커브 움직임 크기
    pk = pd.DataFrame({"open": usd, "high": usd, "low": usd, "close": usd})  # 5분 종가로만 만든 근사
    evc = event(pk, 1.0)
    out["event_curve_FYT"] = {"days": len(evc), "move_median_usd": round(evc.move.median(), 2),
                              "cost_share_vs_move": round(cost_usd / evc.move.median(), 3)}
    out["max_cost_share"] = MAX_COST_SHARE
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (RESULTS / "precheck.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
