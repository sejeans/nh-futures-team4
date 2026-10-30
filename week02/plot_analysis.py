# 6절 결과 분석 차트 3장 (실전 기록 journal_*.jsonl 만 사용)
#   results/analysis_daily.png  일별 손익 (규칙 변경 전/후)
#   results/analysis_stops.png  손절 6회: 손절선 77틱 대비 실제 손실 틱
#   results/analysis_fills.png  시장가 28건: 주문 직전 최우선 호가 대비 체결가
import json

import matplotlib.pyplot as plt
import pandas as pd

from compare_week import C, GRID, INK, MUTED
from fetch_bars import RESULTS
from strategy import P, TICK, WARMUP_FROM

STOP = P["stop_ticks"]


def load_events():
    ev = []
    for d in pd.bdate_range("2026-10-26", "2026-10-30"):
        ev += [json.loads(line) for line in open(RESULTS / f"journal_{d:%Y%m%d}.jsonl", encoding="utf-8")]
    return ev


def clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=INK)


def main():
    ev = load_events()
    ex = pd.DataFrame([e for e in ev if e["event"] == "exit"])
    ex["ts"] = pd.to_datetime(ex.ts)
    ex["ticks"] = ((ex.exit - ex.entry) * ex.side / TICK).round().astype(int)

    # 1) 일별 손익
    day = ex.groupby(ex.ts.dt.normalize()).agg(krw=("pnl", "sum"), n=("pnl", "size"),
                                               stops=("reason", lambda r: (r == "손절").sum()))
    after = day.index >= pd.Timestamp(WARMUP_FROM)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars = ax.bar(day.index.strftime("%m/%d(%a)").str.replace("Mon", "월").str.replace("Tue", "화")
                  .str.replace("Wed", "수").str.replace("Thu", "목").str.replace("Fri", "금"),
                  day.krw / 10_000, color=[C[1] if a else C[0] for a in after], width=0.6)
    for b, (krw, n, s) in zip(bars, day[["krw", "n", "stops"]].values):
        y = b.get_height()
        ax.annotate(f"{krw:+,}원\n{n}회, 손절 {s}회", (b.get_x() + b.get_width() / 2, y),
                    xytext=(0, 4 if y >= 0 else -4), textcoords="offset points", ha="center",
                    va="bottom" if y >= 0 else "top", fontsize=9, color=INK)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_ylim(day.krw.min() / 10_000 * 1.45, day.krw.max() / 10_000 * 1.6)
    ax.set_ylabel("손익 (만원, 수수료 포함)", color=INK)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=C[0], label="변경 전 규칙 (하루 첫 봉만 제외)"),
                       plt.Rectangle((0, 0), 1, 1, color=C[1], label="변경 후 규칙 (당일 봉 20개 대기)")],
              loc="upper left", frameon=False, fontsize=9)
    ax.set_title(f"실전 일별 손익: 5일 {len(ex)}회, 합계 {ex.pnl.sum():+,}원", loc="left", fontsize=11)
    clean(ax)
    fig.tight_layout()
    fig.savefig(RESULTS / "analysis_daily.png", dpi=130)

    # 2) 손절: 손절선 77틱 대비 실제 손실
    st = ex[ex.reason == "손절"].sort_values("ts").reset_index(drop=True)
    entry_t = [pd.Timestamp(e["ts"]) for e in ev if e["event"] == "enter"]
    st["entry_t"] = [max(t for t in entry_t if t <= x) for x in st.ts]
    labels = [f"{r.entry_t:%m/%d %H:%M} {'매수' if r.side > 0 else '매도'}" for r in st.itertuples()]
    loss = -st.ticks
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.barh(labels, [min(v, STOP) for v in loss], color=C[0], height=0.55, label=f"손절선까지 ({STOP}틱)")
    ax.barh(labels, [max(v - STOP, 0) for v in loss], left=STOP, color=C[1], height=0.55,
            label="손절선을 넘은 추가 손실")
    for i, v in enumerate(loss):
        ax.annotate(f"{v}틱 ({v - STOP:+d})", (v, i), xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    ax.axvline(STOP, color=INK, lw=1, ls=(0, (4, 3)))
    ax.invert_yaxis()
    ax.set_xlim(0, loss.max() * 1.18)
    ax.set_xlabel("진입가 대비 손실 틱 (1틱 = 1,000원)", color=INK)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False, fontsize=9)
    ax.set_title(f"손절 {len(st)}회: 현재가를 1분마다 확인해, {(loss > STOP).sum()}회는 손절선보다 더 밀린 뒤 체결",
                 loc="left", fontsize=11)
    clean(ax)
    fig.tight_layout()
    fig.savefig(RESULTS / "analysis_stops.png", dpi=130)

    # 3) 체결가: 주문 직전 최우선 호가(매수는 매도호가, 매도는 매수호가) 대비, + 는 유리
    orders, slip = {}, []
    for e in ev:
        if e["event"] == "order":
            orders[e["ord_no"]] = e
        elif e["event"] == "fill":
            o = orders[e["ord_no"]]
            ref = float(o["book"]["ask"] if o["side"] > 0 else o["book"]["bid"])
            slip.append(round((ref - e["fill"]["px"]) * o["side"] / TICK))
    cnt = pd.Series(slip).value_counts().reindex(range(-1, 3), fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    colors = [C[1] if k < 0 else C[0] if k > 0 else MUTED for k in cnt.index]
    bars = ax.bar([f"{k:+d}틱" if k else "같음" for k in cnt.index], cnt.values, color=colors, width=0.6)
    for b, v in zip(bars, cnt.values):
        ax.annotate(f"{v}건", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=9.5, color=INK)
    ax.annotate("백테스트는 28건 모두\n여기(1틱 불리)로 가정", (0, cnt.iloc[0] + 1.2), xytext=(0, cnt.max() * 0.45),
                ha="center", fontsize=9, color=INK, arrowprops=dict(arrowstyle="->", color=INK, lw=0.8))
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.set_ylabel("주문 수", color=INK)
    ax.set_xlabel("주문 직전 최우선 호가 대비 체결가 (+ 유리, - 불리)", color=INK)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_title(f"시장가 {len(slip)}건 체결가: 불리 {sum(s < 0 for s in slip)}건, 같음 {slip.count(0)}건, "
                 f"유리 {sum(s > 0 for s in slip)}건", loc="left", fontsize=11)
    clean(ax)
    fig.tight_layout()
    fig.savefig(RESULTS / "analysis_fills.png", dpi=130)
    plot_band_widening()
    print("저장: results/analysis_daily.png, analysis_stops.png, analysis_fills.png, analysis_band_1028.png")


def plot_band_widening():
    """10/28 아침: 전일 봉이 섞인 밴드에서 상단 밴드가 올라가며 매도 진입 조건이 충족된 과정 (6절 3번)"""
    from compare_week import WEEK_5M
    from fetch_bars import BARS_5M, load
    n, k = P["bollinger"]["n"], P["bollinger"]["k"]
    b = pd.concat([load(BARS_5M[1], 5), load(WEEK_5M, 5)]).sort_index()
    b = b[~b.index.duplicated() & ~b.auction].set_index("close_t")
    mid = b.close.rolling(n).mean()
    up = mid + k * b.close.rolling(n).std(ddof=P["bollinger"]["std_ddof"])
    w = slice("2026-10-28 08:50", "2026-10-28 10:30")
    today = b.loc["2026-10-28"].groupby(level=0).ngroup()  # 당일 몇 번째 봉인지
    prev_n = (n - (today + 1)).clip(lower=0).reindex(b.loc[w].index)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.plot(b.loc[w].index, up[w], color=C[1], lw=2, label="상단 밴드")
    ax.plot(b.loc[w].index, mid[w], color=MUTED, lw=1.2, ls=(0, (4, 3)), label="중심선 (5분봉 20개 평균)")
    ax.plot(b.loc[w].index, b.close[w], color=INK, lw=1.4, marker="o", ms=3.5, label="5분봉 종가")
    t15, t20 = pd.Timestamp("2026-10-28 09:15"), pd.Timestamp("2026-10-28 09:20")
    ax.annotate(f"09:15 종가 {b.close[t15]:.1f}\n상단 밴드 {up[t15]:.1f} 위", (t15, b.close[t15]), xytext=(-110, 18),
                textcoords="offset points", fontsize=9, color=INK, arrowprops=dict(arrowstyle="->", color=INK, lw=0.8))
    ax.annotate(f"09:20 종가 {b.close[t20]:.1f} (0.4 하락)\n상단 밴드 {up[t20]:.1f}로 올라가\n종가가 밴드 안 → 매도 진입",
                (t20, b.close[t20]), xytext=(25, -70), textcoords="offset points", fontsize=9, color=INK,
                arrowprops=dict(arrowstyle="->", color=INK, lw=0.8))
    for t in [t15, t20]:
        ax.annotate(f"밴드 {n}개 중 전일 봉 {int(prev_n[t])}개", (t, mid[t]), xytext=(0, -16), textcoords="offset points",
                    ha="center", fontsize=8.5, color=MUTED)
    ax.axvline(pd.Timestamp("2026-10-28 10:30"), color=MUTED, lw=0.8, ls=":")
    ax.text(pd.Timestamp("2026-10-28 10:28"), ax.get_ylim()[0] + 2, "10/29부터는\n이 시각부터 진입", ha="right",
            fontsize=8.5, color=MUTED)
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%H:%M"))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.set_title("10/28 아침: 가격이 내려와서가 아니라 밴드가 넓어져서 매도 조건이 충족됨", loc="left", fontsize=11)
    clean(ax)
    fig.tight_layout()
    fig.savefig(RESULTS / "analysis_band_1028.png", dpi=130)


if __name__ == "__main__":
    main()
