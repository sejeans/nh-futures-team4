# 3주차 — 잘 알려진 채권선물 전략을 같은 비용·같은 체결 가정으로 지난 데이터에 돌린다
# 규칙과 숫자는 교과서 기본값 그대로 쓰고 손익을 본 뒤 바꾸지 않는다. 실전(모의) 규칙 LIVE 는 손익을 보기 전에 정했다.
#
# 데이터: overseas/chart-daily, cidx_yn=1 (연결 일봉, ZN 1998~, ZF 2022~). 월물 교체일 갭이 조정 안 된 원가격이라
#         ZN 2022년 이전은 쓰지 않는다: 2001~2007 가격 수준이 70~90(실제 100 이상), 미국 공휴일 봉 13개가 17~37포인트 튐,
#         2021년까지 종가가 고가·저가 밖인 날이 절반 (11/05 연도별 점검). 2022년부터는 그런 날이 0~3%
#         2022-06 ~ 2023-01 은 평일 봉이 빠져 있다 (ZN 143일, ZF 137일) → 2023-01-12 부터 쓴다
#         교체일 밤사이 갭을 빼서 백어저스트한다 (roll_days). 지표 발표 전후는 1분봉(8/24~10/30)으로.
# 체결: 일봉 전략은 종가에 신호 → 다음 거래일 시가에 체결. 모의 서버가 00:00~07:00 닫혀 있어서
#       05:00(정산) 직후 체결이 불가능하므로, 다음 날 장중 체결을 시가로 근사한다.
# 비용: 진입·청산마다 1틱 불리 + 수수료 편도 $8/계약 (11/02 수동 왕복 실측, results/manual_roundtrip_20261102_214821.json)
#       분기 교체 때 보유 중이면 교체 비용(왕복 1회분)을 더 낸다.
import json
from datetime import datetime

import numpy as np
import pandas as pd

from backtest import MAX_COST_SHARE, bars
from fetch_bars import RESULTS, load
from nh_os import SPEC
from precheck import et

FEE_SIDE = 8.0
SLIP = 1
POINT_USD = 1000.0  # ZN·ZF 모두 액면 $100,000 → 가격 1포인트 = $1,000
FYT = {"ZF": 3, "ZN": -2}  # CME 5년·10년 스프레드 기준 비율 (precheck.py 와 같음). +1 = 스티프너
LIVE = "추세_TSMOM_12개월"  # 11/05 17:40, 손익 보기 전에 지정. Moskowitz·Ooi·Pedersen(2012)의 기본 정의
START = "2023-01-12"  # 데이터 품질 기준 시작일 (위 설명)


def side_cost(legs):
    """편도 비용 USD (단위 포지션 1개 기준)"""
    return sum(abs(n) * (SLIP * SPEC[k]["tick_usd"] + FEE_SIDE) for k, n in legs.items())


def daily(name, file=None, until="2026-11-05"):
    """until 날짜 봉부터는 버린다 (진행 중인 봉). 기본값은 11/05 17시 조회본"""
    occ = json.loads((file or RESULTS / f"bars_{name}_cont_1d_20261105.json").read_text(encoding="utf-8"))["data"]
    d = pd.DataFrame(occ).rename(columns=lambda c: c.removeprefix("occurs1_"))
    d.index = pd.to_datetime(d.ref_dt)
    d = d[~d.index.duplicated()].sort_index()
    d = d[["open_pric", "high_pric", "low_pric", "close_pric"]].astype(float)
    d.columns = ["open", "high", "low", "close"]
    return d[(d.index >= START) & (d.index < until)]


def roll_days(d, tick):
    """2·5·8·11월 마지막 8영업일 ~ 다음 달 첫 3영업일 중 밤사이 갭(시가-전일종가)이 가장 큰 날.
    ZF 는 마지막 영업일 하루 전으로 뚜렷하고, ZN 연결 시리즈는 해마다 교체일이 달라 창 안 최댓값으로 잡는다.
    ponytail: 교체 갭이 0에 가까운 분기엔 평범한 날을 고를 수 있다 (그 하루 밤사이 손익만 빠짐). 월물별 일봉이 있으면 정확히 맞춘다"""
    gap = (d.open - d.close.shift()) / tick
    out = []
    for (y, m), g in d.groupby([d.index.year, d.index.month]):
        if m not in (2, 5, 8, 11):
            continue
        nxt = d[(d.index > g.index[-1])].index[:3]
        win = gap.reindex(list(g.index[-8:]) + list(nxt)).dropna()
        if len(win) and len(g) > 5:
            out.append(win.abs().idxmax())
    return pd.DatetimeIndex(out)


def adjust(d, rolls):
    """백어저스트: 교체일 이전 봉 전부에 그 교체 갭을 더한다 → 교체일 밤사이 갭 = 0"""
    gap = pd.Series(0.0, index=d.index)
    gap[rolls] = (d.open - d.close.shift())[rolls]
    off = gap[::-1].cumsum()[::-1].shift(-1, fill_value=0.0)  # 그 날 이후 교체 갭 합
    return d.add(off, axis=0)


def pnl(px, pos, legs, rolls, cost=True):
    """px: {leg: 조정 OHLC}, pos: 종가 기준 목표 포지션(+1/0/-1). 다음 날 시가에 체결.
    일 손익 = 밤사이(전전 신호 포지션) + 장중(전 신호 포지션) − 체결 비용 − 교체 비용"""
    p1, p2 = pos.shift(1).fillna(0), pos.shift(2).fillna(0)
    usd = pd.Series(0.0, index=pos.index)
    for k, n in legs.items():
        o, c = px[k].open.reindex(pos.index), px[k].close.reindex(pos.index)
        usd += n * POINT_USD * (p2 * (o - c.shift()).fillna(0) + p1 * (c - o))
        if cost:
            usd -= p1.index.isin(rolls[k]) * (p1 == p2) * p2.abs() * 2  # 교체일 넘겨 계속 보유할 때만 * abs(n) * (SLIP * SPEC[k]["tick_usd"] + FEE_SIDE)
    if cost:
        usd -= (p1 - p2).abs() * side_cost(legs)
    return usd, p1


def trades(usd_gross, held):
    """같은 포지션이 이어진 구간 = 거래 1건. gross 는 비용 전 가격 움직임 (사전 기준용, 방향 무관 크기)"""
    run = (held != held.shift()).cumsum()
    g = pd.DataFrame({"usd": usd_gross, "held": held, "run": run})[held != 0]
    return g.groupby("run").agg(side=("held", "first"), gross=("usd", "sum"), days=("usd", "size"),
                                start=("usd", lambda s: s.index[0]))


def stats(usd, held, gross, legs):
    tr = trades(gross, held)
    rt = 2 * side_cost(legs)
    net = tr.gross - rt
    eq = usd.cumsum()
    yrs = len(usd) / 252
    med = float(tr.gross.abs().median()) if len(tr) else float("nan")
    return {"기간": f"{usd.index[0]:%Y-%m-%d} ~ {usd.index[-1]:%Y-%m-%d}", "거래": len(tr),
            "연간거래": round(len(tr) / yrs, 1), "평균보유일": round(float(tr.days.mean()), 1) if len(tr) else 0,
            "승률": round(float((net > 0).mean()), 3) if len(tr) else None,
            "손익_usd": round(float(usd.sum()), 0), "연평균_usd": round(float(usd.sum()) / yrs, 0),
            "최대낙폭_usd": round(float((eq - eq.cummax()).min()), 0),
            "샤프(연환산)": round(float(usd.mean() / usd.std() * np.sqrt(252)), 2) if usd.std() else None,
            "왕복비용_usd": round(rt, 2), "거래당움직임중앙_usd": round(med, 2),
            "비용비중": round(rt / med, 3) if med else None,
            "사전기준통과": bool(med and rt / med <= MAX_COST_SHARE),
            "연도별손익_usd": {str(y): round(float(v)) for y, v in usd.groupby(usd.index.year).sum().items()}}


# --- 일봉 신호 (종가 기준 목표 포지션) ---
def tsmom(c, n=252):
    return np.sign(c - c.shift(n)).fillna(0)


def monthly(pos):
    """월말 종가 신호만 쓰고 한 달 유지 (원논문 방식: 월 1회 리밸런싱)"""
    last = pos.index.to_series().groupby(pos.index.to_period("M")).transform("max") == pos.index
    return pos.where(last).ffill().fillna(0)


def ma_cross(c, fast=50, slow=200):
    return np.sign(c.rolling(fast).mean() - c.rolling(slow).mean()).fillna(0)


def donchian(d, entry=20, exit_=10):
    """터틀 System 1: 직전 20일 최고가 돌파 매수 / 최저가 이탈 매도, 반대쪽 10일 극값에서 청산. 종가로 판단"""
    hi_e, lo_e = d.high.rolling(entry).max().shift(), d.low.rolling(entry).min().shift()
    hi_x, lo_x = d.high.rolling(exit_).max().shift(), d.low.rolling(exit_).min().shift()
    pos, out = 0, []
    for c, he, le, hx, lx in zip(d.close, hi_e, lo_e, hi_x, lo_x):
        if pos == 1 and c < lx or pos == -1 and c > hx:
            pos = 0
        if pos == 0:
            pos = 1 if c > he else -1 if c < le else 0
        out.append(pos)
    return pd.Series(out, index=d.index, dtype=float)


def zscore_revert(s, n=20, k=2.0):
    """스프레드가 20일 평균에서 2표준편차 벗어나면 반대로, 평균 복귀 시 청산"""
    z = (s - s.rolling(n).mean()) / s.rolling(n).std()
    pos, out = 0, []
    for v in z:
        if pos == 1 and v >= 0 or pos == -1 and v <= 0:
            pos = 0
        if pos == 0 and not np.isnan(v):
            pos = -1 if v > k else 1 if v < -k else 0
        out.append(pos)
    return pd.Series(out, index=s.index, dtype=float)


# --- 지표 발표 전후 (1분봉) ---
def event_orb(b1, tick, tick_usd):
    """오프닝 레인지 돌파: 8:20~8:35 ET 범위, 8:35~9:45 ET 5분 종가가 범위를 벗어나면 그 방향 진입,
    반대쪽 범위 끝 종가 이탈 시 손절, 9:50 ET 청산 (한국 23:50, 모의 운영 24:00 전). 하루 1회"""
    b5 = et(bars(b1, 5))
    rows = []
    for day, g in b5.groupby(b5.index.date):
        rng = g.between_time("08:20", "08:34")
        after = g.between_time("08:35", "09:49")
        if rng.empty or after.empty:
            continue
        hi, lo = rng.high.max(), rng.low.min()
        pos = 0
        for t, c in after.close.items():
            if not pos and t.strftime("%H:%M") < "09:45":
                pos = 1 if c > hi else -1 if c < lo else 0
                if pos:
                    e = c
                    continue
            if pos and (pos == 1 and c < lo or pos == -1 and c > hi):
                break
        if not pos:
            continue
        ticks = (c - e) * pos / tick  # 비용 전
        rows.append({"day": day, "side": pos, "entry": e, "exit": c, "gross_ticks": round(ticks, 2),
                     "gross": ticks * tick_usd, "usd": (ticks - 2 * SLIP) * tick_usd - 2 * FEE_SIDE})
    return pd.DataFrame(rows)


def selfcheck():
    """1) 교체 갭은 조정 후 밤사이 0  2) 매수 1일 보유: 손익 = 장중 + 다음 밤 − 왕복 비용"""
    i = pd.bdate_range("2026-01-05", periods=5)
    d = pd.DataFrame({"open": [100, 101, 103, 103, 103], "close": [101, 102, 103, 103, 103]}, index=i, dtype=float)
    d[["high", "low"]] = d[["close", "open"]].values
    r = pd.DatetimeIndex([i[2]])  # i[2] 시가 103 vs 전일 종가 102 → 갭 1
    a = adjust(d, r)
    assert a.open[i[2]] - a.close[i[1]] == 0 and a.close[i[0]] == 102
    pos = pd.Series([1, 0, 0, 0, 0], index=i, dtype=float)  # i0 종가 신호 → i1 시가 매수, i1 종가 0 → i2 시가 매도
    usd, _ = pnl({"ZN": a}, pos, {"ZN": 1}, {"ZN": r})
    assert round(usd.sum(), 4) == round(1 * POINT_USD - 2 * side_cost({"ZN": 1}), 4), usd


def main():
    selfcheck()
    raw = {k: daily(k) for k in ("ZN", "ZF")}
    rolls = {k: roll_days(raw[k], SPEC[k]["tick"]) for k in raw}
    px = {k: adjust(raw[k], rolls[k]) for k in raw}
    print("교체일 최근:", {k: [f"{x:%Y-%m-%d}" for x in v[-3:]] for k, v in rolls.items()})

    zn, curve_idx = px["ZN"], px["ZF"].index.intersection(px["ZN"].index)
    spread = sum(n * px[k].close.reindex(curve_idx) for k, n in FYT.items())
    runs = {
        "보유_매수(비교용)": (pd.Series(1.0, index=zn.index), {"ZN": 1}),
        "추세_TSMOM_12개월": (tsmom(zn.close), {"ZN": 1}),
        "추세_TSMOM_12개월_월간": (monthly(tsmom(zn.close)), {"ZN": 1}),  # 11/05 추가: 원논문은 월 1회 리밸런싱
        "추세_이동평균_50_200": (ma_cross(zn.close), {"ZN": 1}),
        "추세_돈치안_20_10": (donchian(zn), {"ZN": 1}),
        "커브_스프레드추세_20일": (tsmom(spread, 20), FYT),
        "커브_스프레드회귀_z2": (zscore_revert(spread), FYT),
    }
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "live": LIVE, "fee_side_usd": FEE_SIDE,
           "slip_ticks": SLIP, "max_cost_share": MAX_COST_SHARE,
           "rolls_recent": {k: [f"{x:%Y-%m-%d}" for x in v[-8:]] for k, v in rolls.items()}, "runs": {}}
    daily_usd = {}
    for name, (pos, legs) in runs.items():
        usd, held = pnl(px, pos, legs, rolls)
        g_only, _ = pnl(px, pos, legs, rolls, cost=False)  # 비용 전 가격 움직임 (사전 기준용)
        start = pos[pos != 0].index[0]
        usd, held, g_only = usd[start:], held[start:], g_only[start:]
        out["runs"][name] = {"전체": stats(usd, held, g_only, legs),
                             "현재포지션(11/04 종가 기준)": int(pos.iloc[-1])}
        daily_usd[name] = usd
        print(name, out["runs"][name])

    b1 = load(RESULTS / "bars_ZNZ26_1m_20260824_20261030.json")
    ev = event_orb(b1, SPEC["ZN"]["tick"], SPEC["ZN"]["tick_usd"])
    rt = 2 * side_cost({"ZN": 1})
    med = float(ev.gross.abs().median())
    out["runs"]["발표전후_레인지돌파"] = {"전체": {
        "기간": f"{ev.day.min()} ~ {ev.day.max()}", "거래": len(ev), "승률": round(float((ev.usd > 0).mean()), 3),
        "손익_usd": round(float(ev.usd.sum()), 0), "왕복비용_usd": round(rt, 2), "거래당움직임중앙_usd": round(med, 2),
        "비용비중": round(rt / med, 3), "사전기준통과": rt / med <= MAX_COST_SHARE}}
    print("발표전후", out["runs"]["발표전후_레인지돌파"])
    ev.to_csv(RESULTS / "strategies_event_trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_usd).to_csv(RESULTS / "strategies_daily_usd.csv", encoding="utf-8-sig")
    (RESULTS / "strategies_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")


if __name__ == "__main__":
    main()
