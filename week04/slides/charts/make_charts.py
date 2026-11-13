"""week04 발표 차트. 실행: week04 폴더에서 python slides/charts/make_charts.py
일별 스프레드는 live.py history()와 같은 방식(15:30 이전 마지막 분봉)으로 만든다.
10일 평균과 표준편차가 실전 로그(11/10~11/12)와 일치하는 것을 확인했다."""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/skills/slides"))
sys.path.insert(0, os.getcwd())
import numpy as np
import pandas as pd
import slidechart as sc
from matplotlib.patches import FancyArrowPatch

from explore import bars, dv01_won
from fetch_bars import RESULTS, load

OUT = "slides/assets"
ORANGE, NAVY, GRAY, INK, SUB = sc.HIGHLIGHT, sc.POINT, sc.BASE, sc.INK, sc.SUB
CIRC = "①②③④⑤"


def merged(sym):
    d = pd.concat([load(p) for p in sorted(RESULTS.glob(f"bars_{sym}_1m_*.json"))])
    return d[~d.index.duplicated(keep="last")].sort_index()


B = bars(merged("A656C000"), merged("A676C000"))
SIG = B[B.index.strftime("%H:%M") <= "15:30"].groupby("day").tail(1).set_index("day")
DAILY = SIG.spread_bp.copy()
LIVE = {}
for d in ("20261110", "20261111", "20261112"):
    for l in open(RESULTS / f"live_{d}.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if e["event"] == "신호":
            LIVE[pd.Timestamp(e["t"][:10])] = e
# 11/12 15:30 값은 분봉 파일이 없으므로 실전 로그 값을 쓴다
DAILY.loc[pd.Timestamp("2026-11-12")] = LIVE[pd.Timestamp("2026-11-12")]["spread_bp"]
MEAN = DAILY.rolling(10).mean().shift(1)
STD = DAILY.rolling(10).std().shift(1)
Z = (DAILY - MEAN) / STD
TR = pd.read_csv(RESULTS / "backtest_trades.csv", parse_dates=["entry_t", "exit_t"])


def dlabels(ax, idx, step=5):
    x = np.arange(len(idx))
    ax.set_xticks(x[::step])
    ax.set_xticklabels([f"{d:%m/%d}" for d in idx[::step]])
    return x


def note(ax, x, y, text, dx=0, dy=0, color=None, ha="left", **kw):
    ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", ha=ha, va="center",
                color=color or INK, fontsize=kw.pop("fontsize", 16), annotation_clip=False,
                arrowprops=kw.pop("arrow", None), **kw)


# 1. 두 금리와 스프레드
def yields():
    s = SIG.loc[:"2026-11-11"]
    fig, ax = sc.figure("wide")
    x = dlabels(ax, s.index)
    y3, y10 = s.y3 * 100, s.y10 * 100
    ax.fill_between(x, y3, y10, color=ORANGE, alpha=0.18, linewidth=0)
    ax.plot(x, y10, color=NAVY, linewidth=3)
    ax.plot(x, y3, color=GRAY, linewidth=3)
    note(ax, x[-1], y10.iloc[-1], f"10년 {y10.iloc[-1]:.2f}%", dx=10, color=NAVY, fontweight="bold")
    note(ax, x[-1], y3.iloc[-1], f"3년 {y3.iloc[-1]:.2f}%", dx=10, color=SUB)
    note(ax, x[0], y10.iloc[0], f"{y10.iloc[0]:.2f}%", dx=-8, ha="right", color=NAVY)
    note(ax, x[0], y3.iloc[0], f"{y3.iloc[0]:.2f}%", dx=-8, ha="right", color=SUB)
    for i, lab in ((0, "시작"), (len(x) - 1, "끝")):
        sp = (y10.iloc[i] - y3.iloc[i]) * 100
        ax.annotate("", (x[i], y10.iloc[i]), (x[i], y3.iloc[i]),
                    arrowprops=dict(arrowstyle="<->", color=ORANGE, lw=2.5))
        if i == 0:
            note(ax, x[i] + 1.2, (y10.iloc[i] + y3.iloc[i]) / 2, f"스프레드\n{sp:.1f}bp", fontweight="bold")
        else:
            note(ax, x[i] - 0.6, y3.min() - 0.04, f"스프레드 {sp:.1f}bp", ha="right", fontweight="bold")
    ax.set_ylabel("내재 금리 (%)")
    ax.set_ylim(3.5, 4.75)
    ax.margins(x=0.06)
    sc.save(fig, f"{OUT}/yields.png")


# 2. DV01 3:1 이면 금리가 같이 1bp 오를 때 손익이 상쇄된다
def hedge():
    dv3, dv10 = dv01_won(103.73, 3), dv01_won(109.12, 10)
    vals = [-3 * dv3, dv10, dv10 - 3 * dv3]
    fig, ax = sc.figure("col")
    names = ["3년 매수\n3계약", "10년 매도\n1계약", "합계"]
    b = ax.bar(names, vals, color=[GRAY, GRAY, NAVY], width=0.56)
    ax.axhline(0, color=SUB, linewidth=1)
    for bb, v in zip(b, vals):
        ax.text(bb.get_x() + bb.get_width() / 2, v + (2500 if v >= 0 else -2500), f"{v:+,.0f}원",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=18,
                fontweight="bold" if bb is b[2] else "normal")
    ax.tick_params(axis="y", labelleft=False)
    ax.set_ylim(-120000, 120000)
    ax.text(0.5, 0.04, "두 금리가 똑같이 1bp 오를 때 (스티프닝 포지션)", transform=ax.transAxes,
            ha="center", color=SUB, fontsize=15)
    sc.save(fig, f"{OUT}/hedge.png")


# 3. 일별 스프레드, 10일 평균, 진입선 + 백테스트 거래 번호
def spread_daily():
    d = DAILY.loc[:"2026-11-09"]
    m, s = MEAN.loc[d.index], STD.loc[d.index]
    fig, ax = sc.figure("wide")
    x = dlabels(ax, d.index)
    ax.fill_between(x, m - 1.5 * s, m + 1.5 * s, color=sc.GRID, alpha=0.8, linewidth=0)
    ax.plot(x, m, color=SUB, linewidth=2, linestyle="--")
    ax.plot(x, d.values, color=NAVY, linewidth=3)
    pos = {day: i for i, day in enumerate(d.index)}
    for k, r in TR.iterrows():
        i0, i1 = pos[pd.Timestamp(r.entry_t.date())], pos[pd.Timestamp(r.exit_t.date())]
        win = r.net_krw > 0
        ax.axvspan(i0, i1, color=ORANGE if win else NAVY, alpha=0.10, linewidth=0)
        ax.scatter(i0, d.iloc[i0], s=130, color=ORANGE, zorder=5, edgecolor="white", linewidth=1.5)
        note(ax, i0, d.iloc[i0], CIRC[k], dy=26 if r.side < 0 else -26, ha="center", fontsize=20,
             fontweight="bold", color=ORANGE)
        note(ax, (i0 + i1) / 2, 41.5, f"{'평균 복귀' if win else '손절'}\n{r.net_krw/10000:+.1f}만", ha="center",
             fontsize=14, color=INK if win else NAVY)
    note(ax, x[-1], d.iloc[-1], "15:30 스프레드", dx=10, color=NAVY, fontweight="bold")
    note(ax, x[-1], m.iloc[-1], "10일 평균", dx=10, color=SUB)
    note(ax, x[-1], (m + 1.5 * s).iloc[-1], "평균 ± 1.5σ", dx=10, color=SUB)
    note(ax, 2, 22, "처음 10일은 평균이 없어\n신호를 계산하지 않음", color=SUB, fontsize=14)
    ax.set_ylabel("bp")
    ax.set_ylim(18, 44)
    ax.margins(x=0.01)
    sc.save(fig, f"{OUT}/spread_daily.png")


# 4. 보유 기간별 비용 비중
def cost_ratio():
    fig, ax = sc.figure("col")
    sc.bar(ax, ["당일", "3일", "5일", "10일"], [78, 34, 22, 17], emphasize=[3], fmt="{:.0f}%")
    ax.axhline(20, color=ORANGE, linewidth=2.5)
    ax.text(3.45, 21.5, "기준 20%", color=INK, ha="right")
    ax.text(1.5, 70, "왕복 비용 0.78bp ÷\n보유 기간 동안의 변동 폭 중앙값", ha="center", color=SUB, fontsize=15)
    sc.save(fig, f"{OUT}/cost_ratio.png")


# 5. 11/12 z 점수 계산 그림
def z_example():
    today = pd.Timestamp("2026-11-12")
    hist = DAILY.loc[:"2026-11-11"].tail(10)
    e = LIVE[today]
    m, s, v = e["mean"], e["std"], e["spread_bp"]
    fig, ax = sc.figure("wide")
    x = np.arange(11)
    ax.plot(x[:10], hist.values, color=GRAY, linewidth=2, marker="o", markersize=9)
    ax.axhline(m, color=SUB, linestyle="--", linewidth=2)
    ax.axhline(m - 1.5 * s, color=ORANGE, linewidth=2.5)
    ax.scatter(10, v, s=260, color=NAVY, zorder=5)
    ax.annotate("", (10, v), (10, m), arrowprops=dict(arrowstyle="->", color=NAVY, lw=3))
    note(ax, 10, m - 1.2, f"{v - m:+.2f}bp\n= 표준편차 {s:.3f} × {e['z']:+.3f}", dx=-18, ha="right",
         color=NAVY, fontweight="bold", fontsize=17)
    note(ax, 10, v, f"11/12 15:30  {v:.3f}bp\nz = {e['z']:+.3f} → 진입 신호", dx=22, color=NAVY, fontweight="bold")
    note(ax, -0.3, m, f"지난 10일 평균 {m:.3f}bp", dy=16, color=SUB, fontsize=15)
    note(ax, -0.3, m - 1.5 * s, f"진입선 = 평균 - 1.5 × 표준편차 = {m - 1.5 * s:.2f}bp", dy=-16, color=INK, fontsize=15)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{d:%m/%d}" for d in hist.index] + ["11/12\n(오늘)"])
    ax.set_ylabel("bp")
    ax.set_xlim(-0.5, 12.6)
    sc.save(fig, f"{OUT}/z_example.png")


# 6. z 점수 추이와 진입, 청산
def z_timeline():
    z = Z.dropna()
    for d, e in LIVE.items():  # 실전 날은 15:30 현재가로 계산한 로그 값
        z.loc[d] = e["z"]
    fig, ax = sc.figure("wide")
    x = dlabels(ax, z.index, step=4)
    ax.axhspan(-1.5, 1.5, color=sc.GRID, alpha=0.5, linewidth=0)
    for yv in (1.5, -1.5):
        ax.axhline(yv, color=ORANGE, linewidth=2)
    ax.axhline(0, color=SUB, linewidth=1.5, linestyle="--")
    ax.plot(x, z.values, color=NAVY, linewidth=2.5, marker="o", markersize=5)
    pos = {d: i for i, d in enumerate(z.index)}
    for k, r in TR.iterrows():
        i0, i1 = pos[pd.Timestamp(r.entry_t.date())], pos[pd.Timestamp(r.exit_t.date())]
        ax.axvspan(i0, i1, color=ORANGE, alpha=0.12, linewidth=0)
        note(ax, i0, z.iloc[i0], CIRC[k], dx=-14, dy=14 if r.side < 0 else -14, ha="center",
             fontsize=19, fontweight="bold", color=ORANGE)
    i = pos[pd.Timestamp("2026-11-12")]
    ax.scatter(i, z.iloc[i], s=200, color=ORANGE, zorder=6, edgecolor=NAVY, linewidth=2)
    note(ax, i, z.iloc[i], "11/12 실전\n첫 신호", dx=-12, dy=-34, ha="right", fontweight="bold", fontsize=15)
    i0 = pos[pd.Timestamp("2026-11-10")]
    ax.axvspan(i0 - 0.5, len(x) - 0.5, color=NAVY, alpha=0.06, linewidth=0)
    note(ax, i0 - 0.3, 2.9, "모의계좌 실전", fontsize=14, color=NAVY)
    note(ax, x[-1] + 1, 1.5, "+1.5 플래트닝 진입", fontsize=15)
    note(ax, x[-1] + 1, -1.5, "-1.5 스티프닝 진입", fontsize=15)
    note(ax, x[-1] + 1, 0, "0 평균 복귀 청산", fontsize=15, color=SUB)
    ax.set_ylim(z.min() - 0.5, 3.4)
    ax.set_xlim(-0.5, len(x) + 5)
    ax.set_ylabel("z-score")
    sc.save(fig, f"{OUT}/z_timeline.png")


# 7. 백테스트 거래 4건의 분봉 경로
def backtest_paths():
    import matplotlib.pyplot as plt
    sc.setup()
    fig, axes = plt.subplots(1, 4, figsize=(16.8, 6.0), dpi=100, sharey=False)
    b = B[~B.auction]
    for k, (ax, r) in enumerate(zip(axes, TR.itertuples())):
        p = b.loc[r.entry_t:r.exit_t].spread_bp
        t = np.arange(len(p))
        stop = r.entry_spread - 4 * r.side
        win = r.net_krw > 0
        ax.plot(t, p.values, color=NAVY, linewidth=1.6)
        ax.axhline(r.entry_spread, color=SUB, linestyle="--", linewidth=1.5)
        ax.axhline(stop, color=ORANGE, linewidth=2)
        ax.scatter([0], [r.entry_spread], s=90, color=ORANGE, zorder=5)
        ax.scatter([len(p) - 1], [p.iloc[-1]], s=90, color=NAVY, marker="X" if not win else "o", zorder=5)
        lo, hi = min(p.min(), stop), max(p.max(), stop)
        ax.set_ylim(lo - 0.8, hi + 0.8)
        dates = list(p.index.date)
        ticks, labs, lastt = [], [], -1e9
        for d in sorted(set(dates)):
            tt = t[dates.index(d)]
            if tt - lastt >= len(p) * 0.22:
                ticks.append(tt)
                labs.append(f"{d:%m/%d}")
                lastt = tt
        ax.set_xticks(ticks)
        ax.set_xticklabels(labs, fontsize=14)
        ax.tick_params(axis="y", labelsize=13)
        side = "스티프닝" if r.side > 0 else "플래트닝"
        ax.set_title(f"{CIRC[k]} {side}  z {r.z:+.2f}", loc="left", fontsize=17, color=INK, fontweight="bold")
        top = r.side > 0  # 손절선이 아래면 결과 글자는 위에
        pad = (hi - lo) * 0.18
        ax.set_ylim(lo - 0.8, hi + 0.8 + pad) if top else ax.set_ylim(lo - 0.8 - pad, hi + 0.8)
        ax.text(0.02, 0.95 if top else 0.04, f"{r.reason}  {r.net_krw:+,}원",
                transform=ax.transAxes, fontsize=15, color=NAVY if not win else INK, fontweight="bold",
                va="top" if top else "bottom")
        ax.text(len(p) - 1, stop, "손절선", ha="right", va="bottom" if r.side < 0 else "top",
                fontsize=13, color=ORANGE)
    axes[0].set_ylabel("스프레드 (bp)")
    sc.save(fig, f"{OUT}/backtest_paths.png")


# 8. 진입선이 스프레드를 따라 내려온다
def threshold():
    d = DAILY.loc["2026-10-20":]
    m, s = MEAN.loc[d.index], STD.loc[d.index]
    fig, ax = sc.figure("wide")
    x = dlabels(ax, d.index, step=2)
    ax.plot(x, m, color=SUB, linewidth=2, linestyle="--")
    ax.plot(x, m - 1.5 * s, color=ORANGE, linewidth=3)
    ax.plot(x, d.values, color=NAVY, linewidth=3, marker="o", markersize=7)
    note(ax, x[-1], m.iloc[-1], "10일 평균", dx=12, color=SUB)
    note(ax, x[-1], (m - 1.5 * s).iloc[-1] + 0.25, "진입선 (평균 - 1.5σ)", dx=12, color=INK)
    note(ax, x[-1], d.iloc[-1] - 0.3, "15:30 스프레드", dx=12, color=NAVY, fontweight="bold")
    for day, lab in (("2026-11-10", "미달\nz -1.395"), ("2026-11-11", "미달\nz -1.217"), ("2026-11-12", "진입 신호\nz -1.733")):
        i = list(d.index).index(pd.Timestamp(day))
        gap = d.iloc[i] - (m - 1.5 * s).iloc[i]
        ax.annotate("", (x[i], (m - 1.5 * s).iloc[i]), (x[i], d.iloc[i]),
                    arrowprops=dict(arrowstyle="-", color=ORANGE if gap < 0 else SUB, lw=2, linestyle=":"))
        note(ax, x[i], max(d.iloc[i], (m - 1.5 * s).iloc[i]) + 1.4, lab, ha="center", fontsize=14,
             color=NAVY if gap < 0 else SUB, fontweight="bold" if gap < 0 else "normal")
    ax.set_ylabel("bp")
    ax.margins(x=0.02)
    sc.save(fig, f"{OUT}/threshold.png")


# 9. 11/12 장중 스프레드와 진입선
def live_1112():
    ev = [json.loads(l) for l in open(RESULTS / "live_20261112.jsonl", encoding="utf-8")]
    t = pd.DataFrame([{"t": pd.Timestamp(e["t"]), "s": e["spread_bp"]} for e in ev if e["event"] in ("틱", "신호")])
    fails = [pd.Timestamp(e["t"]) for e in ev if e["event"] == "시세 실패"]
    sig = LIVE[pd.Timestamp("2026-11-12")]
    line = sig["mean"] - 1.5 * sig["std"]
    fig, ax = sc.figure("wide")
    ax.plot(t.t, t.s, color=NAVY, linewidth=2.2)
    ax.axhline(line, color=ORANGE, linewidth=2.5)
    for f in fails:
        ax.axvline(f, color=sc.GRID, linewidth=3, zorder=0)
    ax.scatter([t.t.iloc[-1]], [t.s.iloc[-1]], s=200, color=ORANGE, edgecolor=NAVY, linewidth=2, zorder=5)
    wb = dict(boxstyle="round,pad=0.2", fc="white", ec="none")
    note(ax, t.t.iloc[-1], t.s.iloc[-1], f"15:30 {sig['spread_bp']:.3f}bp, z {sig['z']:+.3f} → 진입 신호", dx=-20,
         ha="right", fontweight="bold", color=NAVY, bbox=wb)
    note(ax, t.t.iloc[0], line, f"진입선 {line:.2f}bp", dy=-24, fontsize=15, bbox=wb)
    ax.set_ylim(18.45, 19.85)
    note(ax, fails[0], t.s.max(), f"회색 세로줄: 시세 조회 실패 {len(fails)}회", dx=6, dy=-8, color=SUB, fontsize=14)
    ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["x"]).DateFormatter("%H:%M"))
    ax.set_ylabel("bp")
    sc.save(fig, f"{OUT}/live_1112.png")


# 10. chart-minute 응답 시간 (11/09 14:10~14:31)
def latency():
    rows = []
    for l in open(RESULTS / "api_log" / "20261109.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if e["path"].endswith("chart-minute") and "14:10" <= e["ts"][11:16] <= "14:31":
            to = e["status"] is None and "Timeout" in str(e["response"])
            rows.append({"t": pd.Timestamp(e["ts"]), "el": 10.0 if to else e["elapsed"], "to": to})
    r = pd.DataFrame(rows).dropna()
    fig, ax = sc.figure("wide")
    ok, to = r[~r.to], r[r.to]
    ax.scatter(ok.t, ok.el, s=55, color=NAVY, zorder=3)
    ax.scatter(to.t, to.el, s=80, color=ORANGE, marker="x", linewidth=2.5, zorder=4)
    ax.axhline(10, color=ORANGE, linewidth=1.5, linestyle="--")
    ax.set_yscale("log")
    ax.set_yticks([0.1, 0.5, 1, 5, 10, 60])
    ax.set_yticklabels(["0.1초", "0.5초", "1초", "5초", "10초", "60초"])
    note(ax, to.t.iloc[0], 10, f"× 10초 안에 응답 없음 {len(to)}회 / 전체 {len(r)}회", dy=22, color=INK,
         fontweight="bold")
    mx = ok.loc[ok.el.idxmax()]
    note(ax, mx.t, mx.el, f"최대 {mx.el:.1f}초", dx=12, color=NAVY)
    note(ax, r.t.iloc[0], 32, "같은 형식의 요청이 11/10, 11/11 08:50에는 0.13~0.17초", color=SUB, fontsize=15)
    ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["x"]).DateFormatter("%H:%M"))
    ax.set_ylabel("응답 시간")
    sc.save(fig, f"{OUT}/latency.png")


# 11. 금리 커브: 실제 두 날짜 + 스티프닝, 플래트닝 개념도
def curve():
    import matplotlib.pyplot as plt
    sc.setup()
    fig, axes = plt.subplots(1, 3, figsize=(16.8, 6.0), dpi=100, gridspec_kw={"width_ratios": [1.5, 1, 1]})
    s = SIG.loc[:"2026-11-11"]
    a, b = s.iloc[0], s.iloc[-1]
    ax = axes[0]
    for row, col, lw, lab in ((a, GRAY, 3, f"{s.index[0]:%m/%d}"), (b, NAVY, 3.5, f"{s.index[-1]:%m/%d}")):
        y = [row.y3 * 100, row.y10 * 100]
        ax.plot([3, 10], y, color=col, linewidth=lw, marker="o", markersize=11)
        sp = (row.y10 - row.y3) * 1e4
        ax.annotate("", (10.25, y[1]), (10.25, y[0]), arrowprops=dict(arrowstyle="<->", color=ORANGE, lw=2.5))
        ax.annotate("", (3, y[0]), (10.25, y[0]), arrowprops=dict(arrowstyle="-", color=ORANGE, lw=1, linestyle=":"))
        note(ax, 10.5, sum(y) / 2, f"{lab}\n스프레드 {sp:.1f}bp", color=col if col == NAVY else SUB,
             fontweight="bold" if col == NAVY else "normal")
        note(ax, 3, y[0], f"{y[0]:.2f}%", dx=-12, ha="right", color=col if col == NAVY else SUB, fontsize=15)
        note(ax, 10, y[1], f"{y[1]:.2f}%", dy=18, ha="center", color=col if col == NAVY else SUB, fontsize=15)
    ax.set_xticks([3, 10])
    ax.set_xticklabels(["3년", "10년"])
    ax.set_xlim(1, 14.5)
    ax.set_ylabel("금리 (%)")
    ax.set_title("실제 커브: 기울기가 완만해짐", loc="left", fontsize=17, color=INK, fontweight="bold")
    for ax, title, end, col, txt in ((axes[1], "스티프닝: 스프레드 확대", 4.3, ORANGE, "3년 매수 3계약\n10년 매도 1계약\n→ 이익"),
                                     (axes[2], "플래트닝: 스프레드 축소", 3.7, ORANGE, "3년 매도 3계약\n10년 매수 1계약\n→ 이익")):
        ax.plot([3, 10], [3.5, 3.95], color=GRAY, linewidth=3, marker="o", markersize=9)
        ax.plot([3, 10], [3.5, end], color=NAVY, linewidth=3.5, marker="o", markersize=9)
        ax.annotate("", (10, end), (10, 3.95), arrowprops=dict(arrowstyle="->", color=col, lw=3))
        note(ax, 3.3, 4.25, txt, fontsize=15)
        note(ax, 10, 3.95, "이전", dx=14, color=SUB, fontsize=14)
        note(ax, 10, end, "이후", dx=14, color=NAVY, fontsize=14, fontweight="bold")
        ax.set_xticks([3, 10])
        ax.set_xticklabels(["3년", "10년"])
        ax.set_xlim(1.5, 12.5)
        ax.set_ylim(3.3, 4.45)
        ax.tick_params(axis="y", labelleft=False)
        ax.set_title(title, loc="left", fontsize=17, color=INK, fontweight="bold")
    sc.save(fig, f"{OUT}/curve.png")


# 12. DV01 중립: 1bp 동시 상승 손익 + 실제 일별 가격 변화 산점도
def dv01():
    import matplotlib.pyplot as plt
    sc.setup()
    fig, axes = plt.subplots(1, 2, figsize=(16.8, 6.0), dpi=100, gridspec_kw={"width_ratios": [1, 1.2]})
    ax = axes[0]
    dv3, dv10 = dv01_won(103.73, 3), dv01_won(109.12, 10)
    vals = [-3 * dv3, dv10, dv10 - 3 * dv3]
    bars_ = ax.bar(["3년 매수\n3계약", "10년 매도\n1계약", "합계"], vals, color=[GRAY, GRAY, NAVY], width=0.56)
    ax.axhline(0, color=SUB, linewidth=1)
    for bb, v in zip(bars_, vals):
        ax.text(bb.get_x() + bb.get_width() / 2, v + (3000 if v >= 0 else -3000), f"{v:+,.0f}원", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=17, fontweight="bold" if bb is bars_[2] else "normal")
    ax.tick_params(axis="y", labelleft=False)
    ax.set_ylim(-125000, 125000)
    ax.set_title("두 금리가 같이 1bp 오르면", loc="left", fontsize=17, color=INK, fontweight="bold")
    ax = axes[1]
    b = pd.read_csv(RESULTS / "spread_1m.csv")
    b = b[b.auction == False]  # noqa: E712
    d = b.groupby("day")[["close3", "close10"]].last().diff().dropna()
    k = np.polyfit(d.close3, d.close10, 1)[0]
    ax.scatter(d.close3, d.close10, s=70, color=NAVY, alpha=0.8, zorder=3)
    xs = np.linspace(d.close3.min() * 1.1, d.close3.max() * 1.1, 10)
    ax.plot(xs, xs * k, color=ORANGE, linewidth=2.5)
    ax.plot(xs, xs * 3.008, color=SUB, linewidth=1.5, linestyle="--")
    ax.text(0.03, 0.95, f"주황 실선: 실제 기울기 {k:.2f}\n회색 점선: DV01로 계산한 비율 3.01\n두 선이 겹쳐 보임",
            transform=ax.transAxes, va="top", fontsize=16, color=INK,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none"))
    ax.axhline(0, color=sc.GRID, linewidth=1)
    ax.axvline(0, color=sc.GRID, linewidth=1)
    ax.set_xlabel("3년 선물 하루 가격 변화")
    ax.set_ylabel("10년 선물 하루 가격 변화")
    ax.grid(True, axis="both")
    ax.set_title(f"실제 일별 가격 변화 ({len(d)}일, 상관계수 {d.corr().iloc[0, 1]:.2f})", loc="left", fontsize=17,
                 color=INK, fontweight="bold")
    sc.save(fig, f"{OUT}/dv01.png")


# 13. 보유 기간: 스프레드 움직임 vs 왕복 비용, 반감기 곡선
def holding():
    import matplotlib.pyplot as plt
    sc.setup()
    fig, axes = plt.subplots(1, 2, figsize=(16.8, 6.0), dpi=100, gridspec_kw={"width_ratios": [1.15, 1]})
    ax = axes[0]
    labs, mv, cost = ["당일", "3일", "5일", "10일"], [1.01, 2.3, 3.5, 4.63], 0.78
    bars_ = ax.bar(labs, mv, color=[GRAY, GRAY, GRAY, NAVY], width=0.56)
    ax.axhline(cost, color=ORANGE, linewidth=3)
    ax.set_xlim(-0.5, 4.6)
    ax.text(3.36, cost + 0.1, "왕복 비용\n0.78bp", color=INK, fontsize=16, fontweight="bold", ha="left", va="bottom")
    for bb, v, pct in zip(bars_, mv, (78, 34, 22, 17)):  # README 2절 표의 비용 비중
        ax.text(bb.get_x() + bb.get_width() / 2, v + 0.08, f"{v}bp\n비용 {pct}%", ha="center", va="bottom",
                fontsize=16, fontweight="bold" if v == mv[-1] else "normal")
    ax.set_ylim(0, 6.2)
    ax.tick_params(axis="y", labelleft=False)
    ax.set_title("보유 기간별 스프레드 움직임 (중앙값)", loc="left", fontsize=17, color=INK, fontweight="bold")
    ax = axes[1]
    hl = 5.9
    t = np.linspace(0, 15, 200)
    ax.plot(t, 100 * 0.5 ** (t / hl), color=NAVY, linewidth=3)
    for x, lab in ((hl, f"{hl}일 후 50%"), (10, f"10일 후 {100 * 0.5 ** (10 / hl):.0f}%")):
        y = 100 * 0.5 ** (x / hl)
        ax.plot([x, x], [0, y], color=ORANGE if x == 10 else SUB, linestyle=":", linewidth=2)
        ax.scatter([x], [y], s=110, color=ORANGE if x == 10 else NAVY, zorder=5)
        note(ax, x, y, lab, dx=12, dy=14, fontsize=16, fontweight="bold" if x == 10 else "normal")
    ax.set_xlabel("평균에서 벗어난 뒤 지난 거래일")
    ax.set_ylabel("남은 차이 (%)")
    ax.set_ylim(0, 108)
    ax.set_xlim(0, 15.5)
    ax.set_title("평균에서 벗어난 폭이 줄어드는 속도", loc="left", fontsize=17, color=INK, fontweight="bold")
    sc.save(fig, f"{OUT}/holding.png")


if __name__ == "__main__":
    for f in (curve, dv01, holding, yields, hedge, spread_daily, cost_ratio, z_example, z_timeline, backtest_paths, threshold, live_1112, latency):
        f()
        print("ok", f.__name__)
