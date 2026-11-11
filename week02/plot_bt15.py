# 부록 15분봉 볼린저 백테스트(experiments.py 와 같은 가정) → 날짜별 매매 차트 results/backtest15/trades_YYYYMMDD.png
# 사용: python plot_bt15.py   (거래가 있는 날마다 한 장. plot_journal.py --simple 과 같은 모양, 저장본만 읽고 주문 없음)
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import backtest
from compare_week import WEEK_1M, WEEK_5M
from experiments import FEE, bars15
from fetch_bars import BARS_1M, BARS_5M, RESULTS, load
from plot_journal import BAND, INK, MUTED, NUM, SIDE
from strategy import MULT, P, TICK, bollinger

OUT = RESULTS / "backtest15"


def plot_day(day, b, tr):
    d = pd.Timestamp(day)
    lines = []
    fig, (ax, tx) = plt.subplots(2, 1, figsize=(13, 6.2 + 0.24 * len(tr)), gridspec_kw={"height_ratios": [6, 0.24 * len(tr) + 0.4]})
    ax.fill_between(b.index, b.lo, b.up, color=BAND, alpha=0.25, lw=0)
    ax.plot(b.index, b.mid, color=MUTED, lw=1.2, ls=(0, (4, 3)))
    ax.plot(b.index, b.close, color=INK, lw=1.2, marker="o", ms=2.5)
    for i, r in enumerate(tr.itertuples()):
        name, color, mk = SIDE[r.side]
        moved = round((r.exit_px - r.entry_px) * r.side / TICK)
        ax.axvspan(r.entry_t, r.exit_t, color=color, alpha=0.07, lw=0)
        ax.hlines(r.entry_px - r.side * P["stop_ticks"] * TICK, r.entry_t, r.exit_t, color=color, lw=1, ls=(0, (3, 2)))
        ax.plot([r.entry_t, r.exit_t], [r.entry_px, r.exit_px], color=color, lw=2, zorder=4)
        ax.scatter(r.entry_t, r.entry_px, marker=mk, s=110, color=color, edgecolor="white", lw=1.5, zorder=5)
        ax.scatter(r.exit_t, r.exit_px, marker="X" if r.reason == "손절" else "o", s=80, color=color,
                   edgecolor="white", lw=1.5, zorder=5)
        ax.annotate(NUM[i], (r.entry_t, r.entry_px), xytext=(0, -16 * r.side), textcoords="offset points", ha="center",
                    va="center", fontsize=10, color=color, weight="bold", zorder=6, bbox=dict(fc="white", ec="none", pad=0.5, alpha=0.85))
        why = "하단 밴드 아래 → 안 복귀" if r.side > 0 else "상단 밴드 위 → 안 복귀"
        lines.append(f"{NUM[i]} {r.entry_t:%H:%M} {why} → {name} {r.entry_px:.1f}   "
                     f"{r.exit_t:%H:%M} {'운영 종료' if r.reason == '15:25' else '중심선' if r.reason == '신호' else r.reason} → 청산 {r.exit_px:.1f}   "
                     f"{moved:+d}틱, 수수료 포함 {r.krw:+,}원")
    ax.set_xlim(d + pd.Timedelta(hours=8, minutes=55), d + pd.Timedelta(hours=15, minutes=40))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(axis="y", color="#e6e5e1", lw=0.8)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    win = (tr.krw > 0).sum()
    ax.set_title(f"{d:%m/%d}   {len(tr)}회, {win}승 {len(tr) - win}패, 수수료 포함 {tr.krw.sum():+,}원", loc="left", fontsize=11)
    handles = [plt.Line2D([], [], color=c, marker=m, lw=2, label=f"{n} 진입") for n, c, m in SIDE.values()]
    handles += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, label="중심선/15:25 청산"),
                plt.Line2D([], [], color=MUTED, marker="X", lw=0, label="손절 청산"),
                plt.Line2D([], [], color=MUTED, ls=(0, (3, 2)), label=f"손절선 ({P['stop_ticks']}틱, 보유 중에만)"),
                plt.Line2D([], [], color=MUTED, ls=(0, (4, 3)), label="중심선 (15분봉 20개 평균)"),
                plt.Line2D([], [], color=INK, marker="o", ms=3, lw=1.2, label="15분봉 종가"),
                plt.Rectangle((0, 0), 1, 1, fc=BAND, alpha=0.5, label="볼린저 밴드 15분 (20, 2σ)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.965), ncol=5, frameon=False, fontsize=8.5)
    fig.suptitle("15분봉 볼린저 백테스트 (부록): 밴드 밖에서 안으로 복귀하면 진입, 중심선 도달 또는 77틱 손절 시 청산",
                 x=0.01, ha="left", y=0.995, fontsize=12)
    tx.axis("off")
    tx.text(0, 1, "\n".join(lines), va="top", ha="left", fontsize=8.8, linespacing=1.6, transform=tx.transAxes)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = OUT / f"trades_{d:%Y%m%d}.png"
    fig.savefig(out, dpi=150, facecolor="white")
    plt.close(fig)
    return out


def main():
    b1 = pd.concat([load(BARS_1M, 1), load(WEEK_1M, 1)]).sort_index()
    b1 = b1[~b1.index.duplicated()]
    b5 = pd.concat([load(p, 5) for p in BARS_5M] + [load(WEEK_5M, 5)]).sort_index()
    b5 = b5[~b5.index.duplicated()]
    backtest.FEE_KRW = FEE
    b15 = bars15(b5)
    tr = backtest.run(b1, bollinger(b15, warmup=1))
    n, k, ddof = P["bollinger"]["n"], P["bollinger"]["k"], P["bollinger"]["std_ddof"]
    b15["mid"] = b15.close.rolling(n).mean()  # strategy.bollinger 와 같은 식
    sd = b15.close.rolling(n).std(ddof=ddof)
    b15["up"], b15["lo"] = b15.mid + k * sd, b15.mid - k * sd
    b15 = b15.set_index("close_t")
    OUT.mkdir(exist_ok=True)
    for day, g in tr.groupby("day"):
        print(plot_day(day, b15[b15.day == day], g.sort_values("entry_t")), f"{len(g)}회 {g.krw.sum():+,}원")
    print(f"합계 {len(tr)}회 {tr.krw.sum():+,}원, {tr.day.nunique()}일")


if __name__ == "__main__":
    main()
