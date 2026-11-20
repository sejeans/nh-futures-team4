# 5주차 README 차트 (저장된 results/ 파일만 사용, API 호출 없음)
#   results/fig_us_gap.png       2절 미국 밤사이 변동 → KTB10 시가 갭(설명됨) vs 장중 변동(설명 안 됨)
#   results/fig_leadlag.png      2절 장중 1분·5분 시차 상관
#   results/fig_reversal.png     2절 전일 장중 변동 구간별 오늘 장중 평균 (학습·검증 vs 시험)
#   results/fig_yearly.png       2절 연도별 반전 상관과 백테스트 손익
#   results/fig_models.png       2절 후보 모형 검증 구간 비교
#   results/fig_stops.png        3절 손절 폭 비교 (학습·검증만)
#   results/fig_equity.png       5절 백테스트 누적 손익 (학습·검증·시험)
#   results/fig_test_compare.png 5절 시험 구간 비교 기준 대비 누적 손익
#   results/fig_live_week.png    5절 실전 주간 (live_*.jsonl 과 이번 주 1분봉 bars_*_1m_*.json 필요)
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


def fig_yearly(d):
    """연도별 반전 강도(전일 장중 vs 오늘 장중 상관)와 백테스트 손익. 반전이 약해진 것을 한 장으로"""
    t = pd.read_csv(RESULTS / "backtest_trades.csv", index_col=0, parse_dates=True)
    years = list(range(2022, 2027))
    corr = [d[d.index.year == y][["prev_intra", "intra"]].corr().iloc[0, 1] for y in years]
    pnl = [t[t.index.year == y].pnl_krw.sum() / 1e4 for y in years]
    cols = [C[0], C[0], C[2], C[1], C[1]]  # 학습, 학습, 검증, 시험, 시험
    labels = ["2022\n학습", "2023\n학습", "2024\n검증", "2025\n시험", "2026\n시험"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, vals, fmt, title in ((axes[0], corr, "{:+.3f}", "어제 장중과 오늘 장중 변동의 상관 (음수 = 반전)"),
                                 (axes[1], pnl, "{:+,.0f}", "백테스트 손익 (만원, 1계약, 비용 차감)")):
        ax.bar(range(len(years)), vals, color=cols, width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, v, fmt.format(v), ha="center", va="top" if v < 0 else "bottom", color=INK, fontsize=9)
        ax.set_xticks(range(len(years)))
        ax.set_xticklabels(labels, fontsize=9)
        ax.axhline(0, color=INK, lw=0.8)
        ax.set_title(title, color=INK, fontsize=10, loc="left")
        clean(ax)
    axes[0].set_ylim(min(corr) * 1.3, 0.02)
    fig.suptitle("반전은 2022~2024에 뚜렷했고 2025년 이후 약해졌다 (2026은 11/13까지)", color=INK, fontsize=12,
                 x=0.01, ha="left", y=1.03)
    save(fig, "fig_yearly.png")


def fig_models(summary):
    ms = summary["models"]
    names = [m["model"] for m in ms][::-1]
    vals = [m["val_krw_per_day"] / 1e4 for m in ms][::-1]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.barh(names, vals, color=[C[0] if v > 0 else C[1] for v in vals], height=0.55)
    for i, (v, m) in enumerate(zip(vals, ms[::-1])):
        ax.text(v + (0.15 if v >= 0 else -0.15), i, f"{v:+.1f}만원, 적중 {m['val_hit'] * 100:.1f}%",
                va="center", ha="left" if v >= 0 else "right", color=INK, fontsize=9)
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_xlim(min(vals) * 1.6, max(vals) * 2.2)
    ax.set_xlabel("검증 구간(2024) 하루 평균 손익 (만원)", color=MUTED, fontsize=9)
    ax.set_title("후보 모형 비교: ZN을 추가하면 오히려 나빠졌다", color=INK, fontsize=12, loc="left")
    clean(ax, "x")
    save(fig, "fig_models.png")


def fig_stops(d):
    """손절 폭 후보 비교. 학습·검증 구간만 (backtest.py --stops 와 같은 계산)"""
    import importlib.util  # fetch_data 가 week02 를 sys.path 앞에 넣어 'backtest' 이름이 week02 것으로 잡히므로 경로로 읽는다
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("backtest05", Path(__file__).with_name("backtest.py"))
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    daily_trades = bt.daily_trades
    tv = d[d.split != "test"]
    stops = [0.2, 0.3, 0.4, 0.5, None]
    names = ["0.2", "0.3", "0.4", "0.5\n(채택)", "손절 없음"]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    x = np.arange(len(stops))
    for i, sp in enumerate(("fit", "val")):
        vals = [daily_trades(tv, s).query("split == @sp").pnl_krw.sum() / 1e4 for s in stops]
        ax.bar(x + (i - 0.5) * 0.36, vals, width=0.34, color=C[0] if sp == "fit" else C[2], label=SPLIT_NAME[sp])
        for xi, v in zip(x, vals):
            ax.text(xi + (i - 0.5) * 0.36, v, f"{v:+,.0f}", ha="center", va="bottom" if v >= 0 else "top",
                    color=INK, fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=9)
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xlabel("손절 폭 (진입가 대비 가격 포인트, 0.1 = 10만원)", color=MUTED, fontsize=9)
    ax.set_ylabel("누적 손익 (만원)", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("학습 구간에서는 손절 폭이 좁을수록 손익이 줄었다 (시험 구간은 보지 않고 결정)", color=INK, fontsize=12, loc="left")
    clean(ax)
    save(fig, "fig_stops.png")


def fig_test_compare(d):
    """시험 구간: 반전 규칙 vs 매일 매수 vs 전일 방향 추종 누적 손익 (backtest.py baselines 와 같은 계산)"""
    t = pd.read_csv(RESULTS / "backtest_trades.csv", index_col=0, parse_dates=True)
    te = d[d.split == "test"]
    rule = t[t.split == "test"].pnl_krw.reindex(te.index, fill_value=0).cumsum() / 1e4
    buy = ((te.intra - S.COST_PT) * 1e6).cumsum() / 1e4
    follow_side = -pd.Series([S.side(x) for x in te.prev_intra], index=te.index)
    follow = (np.where(follow_side != 0, follow_side * te.intra - S.COST_PT, 0) * 1e6).cumsum() / 1e4
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for s, name, col in ((rule, "전일 장중 반전 (채택)", C[0]), (buy, "매일 장중 매수", MUTED),
                         (pd.Series(follow, index=te.index), "전일 방향 추종", C[1])):
        ax.plot(s.index, s.values, color=col, lw=2 if col == C[0] else 1.4, label=f"{name} {s.iloc[-1]:+,.0f}만원")
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_ylabel("누적 손익 (만원, 1계약, 비용 차감)", color=MUTED, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    ax.set_title("시험 구간(2025-01~2026-11-13): 비교 기준보다는 나았지만 이익은 작다", color=INK, fontsize=12, loc="left")
    clean(ax)
    save(fig, "fig_test_compare.png")


def fig_live_week():
    files = sorted(RESULTS.glob("live_2*.jsonl"))
    days = []
    for f in files:
        recs = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        start = next((r for r in recs if r["event"] == "시작" and not r.get("dry")), None)  # 11/16 은 드라이런 뒤에 실전
        if not start:
            continue
        recs = [r for r in recs if r["t"] >= start["t"]]
        days.append((f.stem[5:], recs, start))
    if not days:
        print("실전 기록 없음 → fig_live_week.png 건너뜀")
        return
    m = load_minute("ktb")
    fig, axes = plt.subplots(1, len(days), figsize=(3.4 * len(days), 4.2), squeeze=False)
    for ax, (day, recs, start) in zip(axes[0], days):
        g = m[(m.index.normalize() == pd.Timestamp(day)) & (m.index.strftime("%H:%M") <= "15:45")]
        if len(g):
            ax.plot(g.index, g.close, color=MUTED, lw=1)
        ent = next((r for r in recs if r["event"] == "진입"), None)
        ext = next((r for r in recs if r["event"] == "청산"), None)
        side = {1: "매수", -1: "매도", 0: "신호 없음"}[start["side"]]
        note = "" if start["side"] else f"\n기준 ±{S.MIN_PREV} 미달"
        if ent:
            st = ent["state"]
            t0 = pd.Timestamp(day + " " + st["entry_t"])
            ax.scatter([t0], [st["entry_px"]], color=C[0] if st["side"] > 0 else C[1], s=60, zorder=3)
            ax.hlines(st["stop_px"], t0, pd.Timestamp(day + " 15:30"), color="#d03b3b", lw=1, ls="--")
            ax.text(t0, st["stop_px"], f" 손절가 {st['stop_px']}", color="#d03b3b", fontsize=8, va="bottom")
            if ext and ext.get("exit_px"):
                ax.scatter([pd.Timestamp(ext["t"])], [ext["exit_px"]], color=INK, marker="x", s=60, zorder=3)
                note = f"\n{ext['pnl_krw_after_fee_est']:+,}원 (수수료 추정 차감)"
            else:  # 청산 기록 없음: 마지막 기록 시각에 프로그램이 멈춘 것
                last = pd.Timestamp(recs[-1]["t"])
                ax.axvline(last, color=INK, lw=1, ls=":")
                ax.text(last, ax.get_ylim()[0], f" {last:%H:%M} 프로그램 중단", color=INK, fontsize=8, va="bottom")
                close = g.close.iloc[-1]
                ax.scatter([g.index[-1]], [close], facecolor="white", edgecolor=INK, s=50, zorder=3)
                note = f"\n미청산, 15:45 {close} 기준 {st['side'] * (close - st['entry_px']) * 1e2:+.0f}만원"
        ax.set_title(f"{day[4:6]}/{day[6:]}  어제 장중 {start['prev_intra']:+.2f} → {side}{note}",
                     color=INK, fontsize=9, loc="left")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
        clean(ax)
    fig.suptitle("실전(모의계좌) 5일: 회색 1분 종가, 주황 점 매도 진입, X 청산, 빨간 점선 손절가", color=INK, fontsize=11,
                 x=0.01, ha="left", y=1.04)
    save(fig, "fig_live_week.png")


def main():
    d = build()
    summary = json.loads((RESULTS / "analysis_summary.json").read_text(encoding="utf-8"))
    fig_us_gap(d)
    fig_leadlag(summary)
    fig_reversal(d[d.prev_intra.notna()])
    fig_yearly(d[d.prev_intra.notna()])
    fig_models(summary)
    fig_stops(d[d.prev_intra.notna()])
    fig_equity()
    fig_test_compare(d[d.prev_intra.notna()])
    fig_live_week()


if __name__ == "__main__":
    main()
