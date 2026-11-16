# 5주차 README 차트 (저장된 results/ 파일만 사용, API 호출 없음)
#   results/fig_us_gap.png       2절 미국 밤사이 변동 → KTB10 시가 갭(설명됨) vs 장중 변동(설명 안 됨)
#   results/fig_leadlag.png      2절 장중 1분·5분 시차 상관
#   results/fig_reversal.png     2절 전일 장중 변동 구간별 오늘 장중 평균 (학습·검증 vs 시험)
#   results/fig_equity.png       5절 백테스트 누적 손익 (학습·검증·시험)
#   results/fig_live_week.png    5절 실전 주간 (live_*.jsonl 이 있을 때)
# 사용: python plot_analysis.py
import json

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import strategy as S
from analysis import build
from fetch_data import RESULTS, load_minute

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
INK, MUTED, GRID = "#52514e", "#8a8984", "#e6e5e1"
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # week04 plot_analysis.py 와 같은 팔레트
SPLIT_NAME = {"fit": "학습 2022~23", "val": "검증 2024", "test": "시험 2025~26.11"}


def clean(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=9)
    if grid:
        ax.grid(axis=grid, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(RESULTS / name, dpi=130, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print("saved", name)


def fig_us_gap(d):
    tr = d[d.split != "test"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharex=True, sharey=True)
    for ax, y, title in ((axes[0], "gap", "KTB10 밤사이 갭 (전일 종가 → 시가)"),
                         (axes[1], "intra", "KTB10 장중 변동 (시가 → 종가)")):
        g = tr[["zret", y]].dropna()
        ax.scatter(g.zret, g[y], s=9, color=C[0], alpha=0.35, lw=0)
        b, a = np.polyfit(g.zret, g[y], 1)
        xs = np.array([g.zret.min(), g.zret.max()])
        ax.plot(xs, a + b * xs, color=C[1], lw=2)
        r2 = np.corrcoef(g.zret, g[y])[0, 1] ** 2
        ax.text(0.03, 0.95, f"기울기 {b:.2f}, R² {r2:.2f}, {len(g)}일", transform=ax.transAxes, va="top",
                color=INK, fontsize=10)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.set_xlabel("ZN 직전 거래일 변동 (가격 포인트)", color=MUTED, fontsize=9)
        ax.axhline(0, color=GRID, lw=1)
        ax.axvline(0, color=GRID, lw=1)
        clean(ax, None)
    axes[0].set_ylabel("KTB10 변동 (가격 포인트)", color=MUTED, fontsize=9)
    fig.suptitle("미국 금리 변동은 시가에 반영되고, 장중 변동은 설명하지 못한다 (2022~2024)",
                 color=INK, fontsize=12, x=0.01, ha="left")
    save(fig, "fig_us_gap.png")


def fig_leadlag(summary):
    ll = summary["minute_leadlag"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, f, name in ((axes[0], "1min", "1분"), (axes[1], "5min", "5분")):
        lags = sorted(ll[f]["corr_by_lag"], key=int)
        vals = [ll[f]["corr_by_lag"][L] for L in lags]
        cols = [C[1] if int(L) == 0 else C[0] for L in lags]
        ax.bar([int(L) for L in lags], vals, color=cols, width=0.6)
        for L, v in zip(lags, vals):
            ax.text(int(L), max(v, 0) + 0.012, f"{v:.2f}", ha="center", color=INK, fontsize=9)
        ax.set_xticks([int(L) for L in lags])
        ax.set_ylim(-0.06, 0.6)
        ax.set_xlabel("시차 (봉). + 는 ZN 이 먼저 움직인 경우, - 는 KTB10 이 먼저", color=MUTED, fontsize=9)
        ax.set_title(f"{name} 수익률 ({ll[f]['n']:,}개)", color=INK, fontsize=11, loc="left")
        ax.axhline(0, color=INK, lw=0.8)
        clean(ax)
    axes[0].set_ylabel("KTB10과 ZN 수익률 상관", color=MUTED, fontsize=9)
    fig.suptitle(f"장중(09:00~15:30) 두 시장은 같은 봉에서만 함께 움직인다 ({ll['period'][0]}~{ll['period'][1]})",
                 color=INK, fontsize=12, x=0.01, ha="left", y=1.03)
    save(fig, "fig_leadlag.png")


def fig_reversal(d):
    edges = [-np.inf, -0.3, -S.MIN_PREV, S.MIN_PREV, 0.3, np.inf]
    labels = ["-0.3 이하", "-0.3~-0.11", "-0.11~0.11\n(거래 안 함)", "0.11~0.3", "0.3 이상"]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = np.arange(len(labels))
    counts = []
    for i, (name, part) in enumerate((("학습, 검증 2022~2024", d[d.split != "test"]), ("시험 2025~2026.11", d[d.split == "test"]))):
        g = part.groupby(pd.cut(part.prev_intra, edges, labels=labels), observed=False).intra
        m, n = g.mean(), g.size()
        counts.append(n.values)
        ax.bar(x + (i - 0.5) * 0.36, m.values, width=0.34, color=C[i], label=name)
        for xi, v in zip(x, m.values):
            ax.text(xi + (i - 0.5) * 0.36, v + (0.003 if v >= 0 else -0.003), f"{v:+.3f}",
                    ha="center", va="bottom" if v >= 0 else "top", color=INK, fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{lab}\n{a}일 / {b}일" for lab, a, b in zip(labels, *counts)], fontsize=9)
    ax.set_ylim(-0.115, 0.115)
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xlabel("어제 장중 변동 (가격 포인트)", color=MUTED, fontsize=9)
    ax.set_ylabel("오늘 장중 변동 평균 (가격 포인트)", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_title("어제 크게 오르면 오늘 장중엔 내리는 경향 (0.01 = 1틱 = 1만원)", color=INK, fontsize=12, loc="left")
    clean(ax)
    save(fig, "fig_reversal.png")


def fig_equity():
    t = pd.read_csv(RESULTS / "backtest_trades.csv", index_col=0, parse_dates=True)
    eq = t.pnl_krw.cumsum() / 1e4
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(eq.index, eq.values, color=C[0], lw=2)
    for sp, start in (("val", "2024-01-01"), ("test", "2025-01-01")):
        ax.axvline(pd.Timestamp(start), color=MUTED, lw=1, ls="--")
    for sp in ("fit", "val", "test"):
        part = t[t.split == sp]
        mid = part.index[len(part) // 2]
        ax.text(mid, eq.max() * 1.02, f"{SPLIT_NAME[sp]}\n{int(part.pnl_krw.sum() / 1e4):+,}만원 · {len(part)}회",
                ha="center", va="bottom", color=INK, fontsize=9)
    ax.set_ylim(min(eq.min(), 0) - 100, eq.max() * 1.25)
    ax.set_ylabel("누적 손익 (만원, 1계약, 비용 차감)", color=MUTED, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_title("일봉 백테스트: 학습 구간 뒤로 이익 속도가 크게 줄었다", color=INK, fontsize=12, loc="left")
    clean(ax)
    save(fig, "fig_equity.png")


def fig_live_week():
    files = sorted(RESULTS.glob("live_2*.jsonl"))
    days = []
    for f in files:
        recs = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        start = next((r for r in recs if r["event"] == "시작"), None)
        if not start or start.get("dry"):
            continue
        days.append((f.stem[5:], recs, start))
    if not days:
        print("실전 기록 없음 → fig_live_week.png 건너뜀")
        return
    m = load_minute("ktb")
    fig, axes = plt.subplots(1, len(days), figsize=(3.2 * len(days), 3.8), sharey=False, squeeze=False)
    for ax, (day, recs, start) in zip(axes[0], days):
        g = m[(m.index.normalize() == pd.Timestamp(day)) & (m.index.strftime("%H:%M") < "15:45")]
        if len(g):
            ax.plot(g.index, g.close, color=MUTED, lw=1)
        ent = next((r for r in recs if r["event"] == "진입"), None)
        ext = next((r for r in recs if r["event"] == "청산"), None)
        if ent:
            st = ent["state"]
            ax.scatter([pd.Timestamp(day + " " + st["entry_t"])], [st["entry_px"]], color=C[0] if st["side"] > 0 else C[1],
                       s=60, zorder=3, label="진입")
        if ext and ext.get("exit_px"):
            ax.scatter([pd.Timestamp(ext["t"])], [ext["exit_px"]], color=INK, marker="x", s=60, zorder=3)
        side = {1: "매수", -1: "매도", 0: "신호 없음"}[start["side"]]
        pnl = ext.get("pnl_krw_after_fee_est") if ext else None
        ax.set_title(f"{day[4:6]}/{day[6:]} 전일 {start['prev_intra']:+.2f} → {side}"
                     + (f"\n{pnl:+,}원(수수료 추정 차감)" if pnl is not None else ""), color=INK, fontsize=9, loc="left")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
        clean(ax)
    fig.suptitle("실전(모의) 일별: 회색 1분 종가, 점 진입(파랑 매수·주황 매도), X 청산", color=INK, fontsize=11,
                 x=0.01, ha="left")
    save(fig, "fig_live_week.png")


def main():
    d = build()
    summary = json.loads((RESULTS / "analysis_summary.json").read_text(encoding="utf-8"))
    fig_us_gap(d)
    fig_leadlag(summary)
    fig_reversal(d[d.prev_intra.notna()])
    fig_equity()
    fig_live_week()


if __name__ == "__main__":
    main()
