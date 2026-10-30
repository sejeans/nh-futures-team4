# 채택하지 않은 추가 실험: 10/26~10/30 백테스트 (README 부록)
# B 변경 후 규칙(당일 봉 20개 대기)을 기준으로 한 가지씩만 바꾼다. 가정은 backtest.py 와 같다
# (1틱 슬리피지, 1분마다 손절 확인, 일일 한도, 15:25 청산) + 수수료 왕복 2,400원
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import backtest
from compare_week import C, INK, WEEK_1M, WEEK_5M, step, style
from fetch_bars import BARS_1M, BARS_5M, RESULTS, load
from plot_journal import MUTED, SIDE
from strategy import MULT, P, TICK, WARMUP, bollinger

FEE = 2400
ADD_TICKS = 38  # 물타기: ATR(14) 중앙값 38.36틱만큼 불리하면 1계약 추가 (params_bollinger.ipynb 3절)


def bars15(b5):
    """5분봉 → 15분봉 (종료 단일가 봉 제외, 표기 = 봉 시작 시각)"""
    g = b5[~b5.auction].resample("15min")
    b = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                      "close": g.close.last(), "oi": g.oi.last()}).dropna()
    b["day"], b["auction"] = b.index.normalize(), False
    b["close_t"] = b.index + pd.Timedelta(minutes=15)
    return b


def inertia(b5):
    """중심선에 닿아도 바로 청산하지 않고, 중심선을 넘은 뒤 종가가 꺾이는 봉에서 청산"""
    sig = bollinger(b5, warmup=WARMUP)
    c, pc = b5.close, b5.close.shift()
    mid = c.rolling(P["bollinger"]["n"]).mean()
    sig["exit_long"] = ((pc >= mid.shift()) & (c < pc)).values
    sig["exit_short"] = ((pc <= mid.shift()) & (c > pc)).values
    return sig


def run_add(b1, sig):
    """물타기: backtest.run 과 같고, 첫 진입가보다 ADD_TICKS 불리하면 1계약 추가(최대 2). 손절은 첫 진입가 기준 77틱"""
    entry = sig.entry[sig.entry != 0].to_dict()
    exits = {1: set(sig.index[sig.exit_long]), -1: set(sig.index[sig.exit_short])}
    slip, trades = backtest.SLIP_TICKS * TICK, []
    for day, g in b1[~b1.auction].groupby("day"):
        side, fills, pnl_day = 0, [], 0.0
        for t, px in zip(g.close_t, g.close):
            hm = t.strftime("%H:%M")
            if side:
                moved = round((px - fills[0]) * side / TICK)
                reason = ("15:25" if hm >= backtest.EXIT_AT else "손절" if moved <= -backtest.STOP_TICKS else
                          "신호" if t in exits[side] else None)
                if reason:
                    out = px - side * slip
                    krw = round(sum((out - f) * side * MULT for f in fills) - FEE * len(fills))
                    trades.append({"day": day, "side": side, "entry_t": e_t, "entry_px": fills[0], "n": len(fills),
                                   "add_t": add_t, "exit_t": t, "exit_px": round(out, 1), "reason": reason, "krw": krw})
                    pnl_day += krw
                    side, fills = 0, []
                elif len(fills) == 1 and moved <= -ADD_TICKS:
                    fills.append(round(px + side * slip, 1))
                    add_t = t
                continue
            s = entry.get(t, 0)
            if s and backtest.ENTRY_FROM <= hm < backtest.ENTRY_UNTIL and pnl_day > -backtest.LOSS_LIMIT:
                side, fills, e_t, add_t = s, [round(px + s * slip, 1)], t, None
    return pd.DataFrame(trades)


def momentum10(b1, b5):
    """5분봉 종가가 직전보다 오르면/내리면, 10분 뒤 1분 종가가 같은 방향으로 더 갔는가"""
    c1 = b1[~b1.auction].set_index("close_t").close
    m = b5[~b5.auction].set_index("close_t")
    d = np.sign(m.close.diff()).where(m.day.eq(m.day.shift()))
    t10 = m.index + pd.Timedelta(minutes=10)
    ok = t10.isin(c1.index) & (t10.strftime("%H:%M") <= "15:25") & d.ne(0).values & d.notna().values
    after = np.sign(c1.reindex(t10[ok]).values - m.close[ok].values) * d[ok].values
    return {"신호": int(ok.sum()), "같은 방향": f"{(after > 0).mean():.0%}", "반대": f"{(after < 0).mean():.0%}",
            "변화 없음": f"{(after == 0).mean():.0%}"}


def volume_by_hour(path):
    """1분 거래량 시간대별 평균. cum_trd_qty 는 이름과 달리 그 1분 동안의 거래량이다(15:45 단일가 봉에 큰 값)"""
    rec = json.loads(path.read_text(encoding="utf-8"))
    occ = pd.DataFrame([o for r in (rec if isinstance(rec, list) else [rec])
                        for o in (r["response"].get("Occurs1") or [])])
    occ["t"] = pd.to_datetime(occ.occurs1_ref_dt + occ.occurs1_exch_tm, format="%Y%m%d%H%M%S")
    q = occ.set_index("t").sort_index().occurs1_cum_trd_qty.astype(float)
    q = q[(q.index.strftime("%H:%M") >= "09:00") & (q.index.strftime("%H:%M") < "15:30")]
    return q.groupby(q.index.hour).mean().round(1)


def plot_trades(b5, res):
    """변형별로 한 줄씩: 5분봉 종가 위에 진입(▲매수 ▼매도)과 청산(● 신호/15:25, X 손절)을 잇는다. 밤 시간은 빼고 봉 순서로 붙인다"""
    b = b5[(b5.day >= "2026-10-26") & ~b5.auction].set_index("close_t")
    x = pd.Series(np.arange(len(b)), index=b.index)

    def at(t):  # 1분 시각 → 그 시각까지 확정된 5분봉 위치
        return x.iloc[max(x.index.searchsorted(t, side="right") - 1, 0)]

    fig, axes = plt.subplots(len(res), 1, figsize=(14, 2.3 * len(res)), sharex=True)
    for ax, (name, tr) in zip(axes, res.items()):
        ax.plot(x.values, b.close.values, color="#b9b8b3", lw=1)
        for r in tr.itertuples():
            _, color, mk = SIDE[r.side]
            x0, x1 = at(r.entry_t), at(r.exit_t)
            ax.axvspan(x0, x1, color=color, alpha=0.08, lw=0)
            ax.plot([x0, x1], [r.entry_px, r.exit_px], color=color, lw=2)
            ax.scatter(x0, r.entry_px, marker=mk, s=70, color=color, edgecolor="white", lw=1, zorder=4)
            ax.scatter(x1, r.exit_px, marker="X" if r.reason == "손절" else "o", s=55, color=color,
                       edgecolor="white", lw=1, zorder=4)
            if pd.notna(getattr(r, "add_t", None)):
                ax.scatter(at(r.add_t), b.close.iloc[at(r.add_t)], marker="D", s=40, facecolor="white",
                           edgecolor=color, lw=1.5, zorder=4)
        win = (tr.krw > 0).sum()
        ax.set_title(f"{name}   {len(tr)}회, {win}승 {len(tr) - win}패, {tr.krw.sum():+,}원", loc="left", fontsize=10.5)
        ax.grid(axis="y", color="#e6e5e1", lw=0.8)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(colors=INK, labelsize=8.5)
        for t in b.groupby("day").head(1).index[1:]:
            ax.axvline(x[t], color=MUTED, lw=0.8, ls=":")
    first = b.groupby("day").head(1).index
    axes[-1].set_xticks([x[t] for t in first], [f"{t:%m/%d} 시작" for t in first])
    handles = [plt.Line2D([], [], color=c, marker=m, lw=2, label=f"{n} 진입") for n, c, m in SIDE.values()]
    handles += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, label="중심선/15:25 청산"),
                plt.Line2D([], [], color=MUTED, marker="X", lw=0, label="손절 청산"),
                plt.Line2D([], [], color=MUTED, marker="D", mfc="white", lw=0, label="물타기 추가 진입"),
                plt.Line2D([], [], color="#b9b8b3", lw=1, label="5분봉 종가")]
    fig.legend(handles=handles, loc="lower left", ncol=6, frameon=False, fontsize=9, bbox_to_anchor=(0.01, 1.0))
    fig.suptitle("추가 실험 매매 시점 10/26~10/30 (백테스트)", x=0.01, ha="left", y=1.04, fontsize=12)
    fig.tight_layout()
    fig.savefig(RESULTS / "trades_experiments.png", dpi=130, bbox_inches="tight")


def main():
    b1 = load(WEEK_1M, 1)
    b5 = pd.concat([load(BARS_5M[1], 5), load(WEEK_5M, 5)]).sort_index()
    b5 = b5[~b5.index.duplicated()]
    backtest.FEE_KRW = FEE

    runs = {"기준: B 변경 후 규칙": lambda: backtest.run(b1, bollinger(b5, warmup=WARMUP)),
            "15분봉 (하루 첫 봉만 제외)": lambda: backtest.run(b1, bollinger(bars15(b5), warmup=1)),
            "13:30 이후 신규 진입 금지": None,
            f"물타기 ({ADD_TICKS}틱 불리 시 1계약 추가)": lambda: run_add(b1, bollinger(b5, warmup=WARMUP)),
            "중심선 도달 후 꺾일 때 청산": lambda: backtest.run(b1, inertia(b5))}
    res = {}
    for name, f in runs.items():
        if f is None:
            backtest.ENTRY_UNTIL = "13:30"
            tr = backtest.run(b1, bollinger(b5, warmup=WARMUP))
            backtest.ENTRY_UNTIL = P["entry_window_close_time"][1]
        else:
            tr = f()
        res[name] = tr
        day = tr.groupby(tr.day.dt.strftime("%m/%d")).krw.sum().to_dict()
        print(f"{name}: {len(tr)}회, 승률 {(tr.krw > 0).mean():.0%}, 손절 {(tr.reason == '손절').sum()}회, "
              f"{tr.krw.sum():+,}원 | 일별 {day}")
    add = res[f"물타기 ({ADD_TICKS}틱 불리 시 1계약 추가)"]
    print("물타기 2계약이 된 거래:\n", add[add.n == 2][["entry_t", "side", "exit_t", "reason", "krw"]].to_string(index=False))

    print("\n10분 관성 (이번 주):", momentum10(b1, b5))
    b5_old = pd.concat([load(p, 5) for p in BARS_5M]).sort_index()
    print("10분 관성 (9/11~10/23):", momentum10(load(BARS_1M, 1), b5_old))
    print("\n시간대별 1분 평균 거래량 (이번 주):", volume_by_hour(WEEK_1M).to_dict())
    print("시간대별 1분 평균 거래량 (9/11~10/23):", volume_by_hour(BARS_1M).to_dict())

    fig, ax = plt.subplots(figsize=(11, 5))
    for color, (name, tr) in zip(C, res.items()):
        step(ax, tr.sort_values("exit_t").reset_index(drop=True), color, f"{name} {tr.krw.sum():+,}원", end_label=False)
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m/%d"))
    style(ax, f"추가 실험 누적 손익 10/26~10/30 (백테스트, 수수료 {FEE:,}원)")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(RESULTS / "cum_experiments.png", dpi=130)
    plot_trades(b5, res)
    print("\n저장: results/cum_experiments.png, results/trades_experiments.png")


if __name__ == "__main__":
    main()
