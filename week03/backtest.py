# 3주차 백테스트 — 2주차 후보 B(볼린저 평균회귀, 10/29 이후 규칙)를 ZN 에 옮긴다
# 규칙은 그대로, 숫자(손절·일일 한도)는 2주차와 같은 방법으로 선택 구간에서 다시 정한다.
# 봉 길이는 수익률을 보기 전에 정한 기준(MAX_COST_SHARE)으로 고른다. 1분봉을 따라가며 매 분 손절을 확인한다.
import json
from datetime import datetime

import numpy as np
import pandas as pd

from fetch_bars import RESULTS, load
from nh_os import SPEC

SYM = "ZNZ26"
TICK, TICK_USD = SPEC["ZN"]["tick"], SPEC["ZN"]["tick_usd"]
BARS_1M = RESULTS / f"bars_{SYM}_1m_20260824_20261030.json"
PERIODS = {"선택": ("2026-09-01", "2026-10-16"), "검증": ("2026-10-19", "2026-10-30")}

# 2주차와 같은 값 (week02/results/params_bollinger.json, week02/strategy.py)
N, K, DDOF, WARMUP = 20, 2.0, 0, 20
ATR_N, STOP_K, LOSS_STOPS = 14, 2.0, 2
SLIP_TICKS = 1                   # 진입·청산마다 1틱 불리
COST_TICKS = 2 * SLIP_TICKS      # 왕복 비용 (수수료 제외)
FEE_USD = 0.0                    # 왕복 수수료: 11/02 수동 왕복으로 실측 전. 손익분기 수수료를 따로 보고한다

# 3주차에 바뀐 값
OPEN_AT, ENTRY_UNTIL, EXIT_AT = "07:00", "23:40", "23:50"   # 모의 해외 운영 07:00~24:00 (과제 공지)
CANDIDATES = [5, 10, 15, 30]     # 분. 30분을 넘으면 당일 봉 20개 대기가 모의 운영 시간을 거의 다 쓴다
MAX_COST_SHARE = 0.2             # 왕복 비용 ≤ 진입 시점 중심선까지 거리 중앙값의 20%. 11/01 수익률을 보기 전에 정함
SESSIONS = [("아시아", "07:00", "16:00"), ("런던", "16:00", "22:20"), ("미국", "22:20", "23:50")]


def bars(b1, m):
    """1분봉 → m분봉. 시각은 봉 시작 시각 (API 5분봉과 같은 방식, 11/01 1분봉 대조로 확인)"""
    b = (b1.resample(f"{m}min", label="left", closed="left")
         .agg({"open": "first", "high": "max", "low": "min", "close": "last", "vol": "sum", "biz": "first"})
         .dropna(subset=["close"]))
    b["close_t"] = b.index + pd.Timedelta(minutes=m)
    return b


def bollinger(b):
    """2주차 후보 B. 직전 종가 밴드 밖 → 이번 종가 밴드 안 복귀 시 진입, 중심선 도달 시 청산.
    전일 봉을 이어서 밴드를 계산하고, 진입은 그 거래일(CME 해외영업일) 봉이 WARMUP 개 쌓인 다음 봉부터"""
    c, pc = b.close, b.close.shift()
    mid = c.rolling(N).mean()
    sd = c.rolling(N).std(ddof=DDOF)
    up, lo = mid + K * sd, mid - K * sd
    ok = b.groupby("biz").cumcount() >= WARMUP
    long_ = ok & (pc < lo.shift()) & (c >= lo)
    short = ok & (pc > up.shift()) & (c <= up)
    return pd.DataFrame({"entry": long_.astype(int) - short.astype(int), "exit_long": c >= mid,
                         "exit_short": c <= mid, "dist": (mid - c).abs() / TICK}).set_index(b.close_t)


def atr_ticks(b):
    pc = b.close.shift()
    tr = pd.concat([b.high - b.low, (b.high - pc).abs(), (b.low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_N).mean() / TICK


def in_window(t, start, end):
    hm = np.asarray(pd.DatetimeIndex(t).strftime("%H:%M"))
    return (hm >= start) & (hm < end)


def check(b, sig):
    """수익률을 보지 않는 점검값: 신호 수, 진입 시점 중심선까지 거리, 비용 비중"""
    s = sig[(sig.entry != 0) & in_window(sig.index, OPEN_AT, ENTRY_UNTIL)]
    days = b.biz.nunique()
    dist = float(s.dist.median()) if len(s) else float("nan")
    return {"signals_per_day": round(len(s) / days, 2), "median_dist_to_mid_ticks": round(dist, 2),
            "cost_share": round(COST_TICKS / dist, 3) if dist else None}


def run(b1, sig, stop, limit, fee=FEE_USD):
    """b1: 1분봉(close_t, close), sig: 봉 마감 시각 기준 신호. 신호 봉 마감 시각의 1분 종가로 체결한다고 본다"""
    entry = sig.entry[sig.entry != 0].to_dict()
    exits = {1: set(sig.index[sig.exit_long]), -1: set(sig.index[sig.exit_short])}
    trades = []
    b1 = b1[in_window(b1.close_t, OPEN_AT, "24:00")]
    for day, g in b1.groupby(b1.close_t.dt.normalize()):
        pos, pnl_day = 0, 0.0
        for t, px in zip(g.close_t, g.close):
            hm = t.strftime("%H:%M")
            if pos:
                reason = (EXIT_AT if hm >= EXIT_AT else
                          "손절" if round((px - e_px) * pos / TICK) <= -stop else
                          "신호" if t in exits[pos] else None)
                if reason:
                    x_px = px - pos * SLIP_TICKS * TICK
                    usd = (x_px - e_px) * pos / TICK * TICK_USD - fee
                    trades.append({"day": day, "side": pos, "entry_t": e_t, "entry_px": e_px, "exit_t": t,
                                   "exit_px": x_px, "reason": reason, "ticks": round((x_px - e_px) * pos / TICK),
                                   "usd": usd})
                    pnl_day += usd
                    pos = 0
                continue  # 보유 중이거나 방금 청산한 봉에서는 진입하지 않는다
            side = entry.get(t, 0)
            # 일일 한도: 다음 거래가 손절되더라도 한도를 넘지 않을 때만 진입 (2주차 README 7절 개선 사항)
            if side and OPEN_AT <= hm < ENTRY_UNTIL and pnl_day - stop * TICK_USD - fee >= -limit:
                pos, e_t, e_px = side, t, px + side * SLIP_TICKS * TICK
        assert pos == 0 or hm < EXIT_AT, "23:50 청산 누락"
        if pos:  # 데이터가 23:50 전에 끝난 날 (10/30 은 24:00 까지만 있다)
            x_px = px - pos * SLIP_TICKS * TICK
            trades.append({"day": day, "side": pos, "entry_t": e_t, "entry_px": e_px, "exit_t": t, "exit_px": x_px,
                           "reason": "데이터끝", "ticks": round((x_px - e_px) * pos / TICK),
                           "usd": (x_px - e_px) * pos / TICK * TICK_USD - fee})
    return pd.DataFrame(trades)


def summary(tr, days):
    if tr.empty:
        return {"거래": 0}
    eq = np.concatenate([[0], tr.usd.cumsum()])
    win, loss = tr.usd[tr.usd > 0], tr.usd[tr.usd <= 0]
    return {"거래": len(tr), "하루거래": round(len(tr) / days, 2), "승률": round(len(win) / len(tr), 3),
            "손익_usd": round(tr.usd.sum(), 2), "평균이익_usd": round(win.mean(), 2) if len(win) else 0,
            "평균손실_usd": round(loss.mean(), 2) if len(loss) else 0,
            "최대낙폭_usd": round(float((eq - np.maximum.accumulate(eq)).min()), 2),
            "청산사유": tr.reason.value_counts().to_dict(),
            "손익분기_왕복수수료_usd": round(tr.usd.sum() / len(tr) + FEE_USD, 2)}


def by_session(tr):
    out = {}
    for name, a, b in SESSIONS:
        s = tr[in_window(tr.entry_t, a, b)] if len(tr) else tr
        out[name] = {"거래": len(s), "손익_usd": round(s.usd.sum(), 2) if len(s) else 0}
    return out


def selfcheck():
    """매수 진입 후 손절선까지 밀리면 손절. 손절틱은 진입 체결가(슬리피지 포함)에서 재므로 손익 = -(손절틱 + 청산 슬리피지)"""
    t = pd.date_range("2026-09-01 10:00", periods=4, freq="1min")
    b1 = pd.DataFrame({"close_t": t, "close": [100.0, 100.0, 100 - 3 * TICK, 100 - 4 * TICK]})
    sig = pd.DataFrame({"entry": [1], "exit_long": [False], "exit_short": [False]}, index=[t[0]])
    tr = run(b1, sig, stop=4, limit=1e9)
    assert list(tr.reason) == ["손절"] and tr.ticks[0] == -(4 + 1), tr
    assert run(b1, sig, stop=4, limit=4 * TICK_USD - 1).empty  # 한도가 손절 1회분보다 작으면 진입 안 함


def main():
    selfcheck()
    b1 = load(BARS_1M)
    b1["close_t"] = b1.index + pd.Timedelta(minutes=1)
    sel = slice(*PERIODS["선택"])

    # 1) 수익률을 보기 전: 봉 길이별 점검값과 손절·한도 숫자 (선택 구간만)
    params = {}
    for m in CANDIDATES:
        b = bars(b1, m)
        atr = float(atr_ticks(b)[sel].median())
        stop = int(round(STOP_K * atr))
        params[m] = {"bar_minutes": m, "atr_median_ticks": round(atr, 2), "stop_ticks": stop,
                     "daily_loss_limit_usd": LOSS_STOPS * stop * TICK_USD, **check(b[sel], bollinger(b)[sel])}
        print(params[m])
    ok = [m for m in CANDIDATES if params[m]["cost_share"] and params[m]["cost_share"] <= MAX_COST_SHARE]
    chosen = ok[0] if ok else None
    print(f"기준 비용 비중 ≤ {MAX_COST_SHARE}: 통과 {ok} → 선택 {chosen}분봉")

    # 2) 손익: 2주차 그대로(5분봉)와 선택한 봉 길이
    result = {"generated_at": datetime.now().isoformat(timespec="seconds"), "fee_usd": FEE_USD,
              "slip_ticks": SLIP_TICKS, "max_cost_share": MAX_COST_SHARE, "params": params, "chosen": chosen, "runs": {}}
    all_tr = []
    for m in dict.fromkeys([5, chosen] if chosen else [5]):
        p, b = params[m], bars(b1, m)
        tr = run(b1, bollinger(b), p["stop_ticks"], p["daily_loss_limit_usd"])
        tr["bar_minutes"] = m
        all_tr.append(tr)
        for name, (a, z) in PERIODS.items():
            t = tr[(tr.day >= a) & (tr.day <= z)] if len(tr) else tr
            days = b1[a:z].close_t.dt.normalize().nunique()
            r = {**summary(t, days), "시간대별": by_session(t)}
            result["runs"][f"{m}분_{name}"] = r
            print(f"{m}분봉 {name}:", r)
    pd.concat(all_tr).to_csv(RESULTS / "backtest_trades.csv", index=False, encoding="utf-8-sig")
    (RESULTS / "backtest_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
