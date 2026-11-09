# 4주차 탐색: 3년·10년 국채선물 분봉 → 내재 금리 → (10년 − 3년) 스프레드가 장중에 얼마나 움직이고 되돌아오는지
# 전략 규칙을 정하기 전에 보는 기초 통계. 진입·청산 규칙은 여기서 고르지 않는다
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from fetch_bars import KTB3, KTB10, RESULTS, load

MULT = 1_000_000  # price 응답 mltplr (2026-11-08). 0.01 = 10,000원
YEARS = {KTB3: 3, KTB10: 10}


def price(y, n):
    """국채선물 가격 = 표면금리 5%·6개월 이표·만기 n년 가상 국채의 가격 (KRX 최종결제가격 산식) [KRX 명세 원문 확인 필요]"""
    d = 1 + y / 2
    return sum(2.5 / d ** i for i in range(1, 2 * n + 1)) + 100 / d ** (2 * n)


def implied_yield(px, n):
    # 가격은 0.01 단위라 종류가 적다 → 고유값만 풀어서 붙인다
    u = {p: brentq(lambda y: price(y, n) - p, 1e-4, 0.3) for p in np.unique(px)}
    return np.array([u[p] for p in px])


def dv01_won(px, n):
    y = implied_yield(np.array([px]), n)[0]
    return (price(y - 1e-4, n) - price(y + 1e-4, n)) / 2 * MULT


def bars(b3, b10):
    """경로 또는 이미 읽은 봉 DataFrame 두 개 → 같은 분 봉만 남긴 스프레드 표"""
    b3, b10 = (load(x) if isinstance(x, (str, Path)) else x for x in (b3, b10))
    b = b3[["close", "day", "auction"]].join(b10[["close"]], how="inner", lsuffix="3", rsuffix="10")
    for s, c in ((KTB3, "close3"), (KTB10, "close10")):
        b[f"y{YEARS[s]}"] = implied_yield(b[c].to_numpy(), YEARS[s])
    b["spread_bp"] = (b.y10 - b.y3) * 1e4
    return b


def half_life(x):
    """AR(1) 계수로 본 평균 회귀 반감기(봉 수). 회귀하지 않으면 inf"""
    x = x.dropna()
    dx, lag = x.diff().iloc[1:], x.shift().iloc[1:]
    beta = np.polyfit(lag - lag.mean(), dx, 1)[0]
    return float(-np.log(2) / np.log(1 + beta)) if beta < 0 else float("inf")


def main(path3, path10):
    b = bars(path3, path10)
    b = b[~b.auction]
    days = b.groupby("day")
    out = {"bars": len(b), "days": days.ngroups, "first": f"{b.index[0]}", "last": f"{b.index[-1]}"}

    # 1) 헤지 비율: DV01 비율 vs 1분 가격 변화 회귀
    last = b.iloc[-1]
    dv3, dv10 = dv01_won(last.close3, 3), dv01_won(last.close10, 10)
    d = b[["close3", "close10"]].groupby(b.day).diff().dropna()  # 날 넘어가는 변화는 뺀다
    out["dv01_won"] = {"3y": round(dv3), "10y": round(dv10), "ratio": round(dv10 / dv3, 3)}
    out["beta_1m_price"] = round(float(np.polyfit(d.close3, d.close10, 1)[0]), 3)  # 3년 0.01 움직일 때 10년 몇
    out["corr_1m_price"] = round(float(d.corr().iloc[0, 1]), 3)

    # 2) 스프레드 움직임 (bp)
    s = b.spread_bp
    daily = days.spread_bp.agg(lambda x: x.max() - x.min())
    oc = days.spread_bp.agg(lambda x: x.iloc[-1] - x.iloc[0])
    close = days.spread_bp.last()
    m5 = s.groupby(b.day).apply(lambda x: x.iloc[::5]).droplevel(0)
    out["spread_bp"] = {
        "level_last": round(float(s.iloc[-1]), 2), "level_min": round(float(s.min()), 2), "level_max": round(float(s.max()), 2),
        "intraday_range_median": round(float(daily.median()), 2),
        "open_to_close_abs_median": round(float(oc.abs().median()), 2),
        "close_to_close_abs_median": round(float(close.diff().abs().median()), 2),
        "chg_5m_std": round(float(m5.groupby(m5.index.normalize()).diff().std()), 3),
    }
    # 3) 평균 회귀: 장중(5분 간격)과 일별 종가
    out["half_life"] = {"intraday_5m_bars": round(float(np.median([half_life(g) for _, g in m5.groupby(m5.index.normalize())])), 1),
                        "daily_close_days": round(half_life(close), 1)}
    # 4) 비용 감: 1bp 스프레드 변화 = 10년 1계약 DV01 (3:1 묶음에서 10년 다리 기준)
    out["bp_value_won_per_10y_contract"] = round(dv10)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    (RESULTS / "explore_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    b.to_csv(RESULTS / "spread_1m.csv")
    return out


def selfcheck():
    assert abs(price(0.05, 3) - 100) < 1e-9 and abs(price(0.05, 10) - 100) < 1e-9  # 쿠폰 = 금리면 액면
    y = implied_yield(np.array([103.85]), 3)[0]
    assert abs(price(y, 3) - 103.85) < 1e-9
    assert half_life(pd.Series(np.cumsum(np.ones(50)))) == float("inf")


if __name__ == "__main__":
    selfcheck()
    main(*sys.argv[1:3])
