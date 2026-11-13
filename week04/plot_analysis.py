# 4주차 README 차트 7장 (저장된 분봉, 실전 기록, API 로그만 사용. API 호출 없음)
#   results/fig_spread_level.png   2절 3년, 10년 역산 금리와 스프레드 (9/11~11/13)
#   results/fig_hedge_ratio.png    2절 3년 대비 10년 가격 변화: 회귀 기울기와 DV01 비율
#   results/fig_cost_screen.png    2절 비용 기준(20%) 후보 비교
#   results/fig_backtest.png       5절 백테스트: 스프레드와 진입 기준선, z, 거래별 손익
#   results/fig_live_week.png      5절 실전 5일: 1분 스프레드와 그날 진입 기준선
#   results/fig_order_1112.png     6절 11/12 첫 다리 주문 경과
#   results/fig_api_health.png     7절 일별 API 호출과 오류
# 사용: python plot_analysis.py
import json
from collections import Counter

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import backtest
import strategy as S
from explore import bars, dv01_won
from fetch_bars import KTB3, KTB10, RESULTS, load

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
INK, MUTED, GRID = "#52514e", "#8a8984", "#e6e5e1"
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]  # week02/compare_week.py 와 같은 팔레트
BP_WON = 86_602  # 3:1 한 세트에서 스프레드 1bp (explore_summary.json)
COST_BP = S.COST_KRW / BP_WON
LIVE_DAYS = ["20261109", "20261110", "20261111", "20261112", "20261113"]
WD = "월화수목금"


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
    fig.savefig(RESULTS / name, dpi=130, facecolor="white")
    plt.close(fig)
    print("saved", name)


def all_bars():
    def merged(sym):
        d = pd.concat([load(p) for p in sorted(RESULTS.glob(f"bars_{sym}_1m_*.json"))])
        return d[~d.index.duplicated(keep="last")].sort_index()
    b = bars(merged(KTB3), merged(KTB10))
    return b[~b.auction]


def signal_rows(b):
    """날마다 15:30 이전 마지막 봉 (backtest.run, live.history 와 같은 기준)"""
    return b[b.index.strftime("%H:%M") <= S.SIGNAL_TM].groupby("day").tail(1).set_index("day")


def live(day):
    recs = [json.loads(x) for x in open(RESULTS / f"live_{day}.jsonl", encoding="utf-8")]
    for r in recs:
        r["t"] = pd.Timestamp(r["t"])
    return recs


# ---------- 2절 ----------
def fig_spread_level(sig):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, height_ratios=[1, 1.15])
    x = np.arange(len(sig))
    for col, c, name in (("y10", C[1], "10년"), ("y3", C[0], "3년")):
        a1.plot(x, sig[col] * 100, color=c, lw=2)
        a1.annotate(f"{name} {sig[col].iloc[-1] * 100:.2f}%", (x[-1], sig[col].iloc[-1] * 100), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK)
        a1.annotate(f"{sig[col].iloc[0] * 100:.2f}%", (0, sig[col].iloc[0] * 100), xytext=(0, 6),
                    textcoords="offset points", ha="left", fontsize=9, color=INK)
    a1.set_ylabel("선물 역산 금리 (%)", color=INK)
    a1.set_title("3년, 10년 국채선물 역산 금리와 스프레드 (매일 15:30 기준, 9/11~11/13)", loc="left", fontsize=11)
    a2.fill_between(x, sig.spread_bp, sig.spread_bp.min() - 3, color=C[2], alpha=0.15, lw=0)
    a2.plot(x, sig.spread_bp, color=C[2], lw=2)
    for i in (0, int(np.argmin(sig.spread_bp.values)), len(sig) - 1):
        a2.plot(i, sig.spread_bp.iloc[i], "o", color=C[2], ms=6, mec="white", mew=1.5)
        a2.annotate(f"{sig.index[i]:%m/%d} {sig.spread_bp.iloc[i]:.1f}bp", (i, sig.spread_bp.iloc[i]),
                    xytext=(0, 9) if i == 0 else (-6, -15) if i < len(sig) - 1 else (8, -3), textcoords="offset points",
                    ha="right" if 0 < i < len(sig) - 1 else "left", fontsize=9, color=INK)
    a2.set_ylabel("스프레드 = 10년 - 3년 (bp)", color=INK)
    a2.set_ylim(sig.spread_bp.min() - 3, sig.spread_bp.max() + 3)
    step = 5
    a2.set_xticks(x[::step], [d.strftime("%m/%d") for d in sig.index[::step]])
    for a in (a1, a2):
        clean(a)
        a.set_xlim(-0.5, len(sig) + 3.5)
    fig.tight_layout()
    save(fig, "fig_spread_level.png")


def fig_hedge_ratio(b):
    last = b[b.index <= "2026-11-09 14:27"].iloc[-1]
    ratio = dv01_won(last.close10, 10) / dv01_won(last.close3, 3)
    px = b[["close3", "close10"]]
    # 30분: 전체를 30분 단위로 나눈 마지막 가격의 차이(밤사이 변화 포함). 1일: 그날 마지막 봉의 차이. README 2절 표와 같은 계산
    m30 = px.resample("30min").last().dropna().diff().dropna()
    sets = [("1분 간격", px.groupby(b.day).diff().dropna()), ("30분 간격", m30),
            ("1일 간격", px.groupby(b.day).last().diff().dropna())]
    intraday30 = px.groupby(b.day).apply(lambda g: g.resample("30min").last().diff().dropna()).droplevel(0)
    print("30분 장중 변화만:", round(float(np.polyfit(intraday30.close3, intraday30.close10, 1)[0]), 2),
          round(float(intraday30.corr().iloc[0, 1]), 2), len(intraday30))
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.9))
    out = {}
    for ax, (name, d) in zip(axes, sets):
        beta = float(np.polyfit(d.close3, d.close10, 1)[0])
        corr = float(d.corr().iloc[0, 1])
        out[name] = (round(beta, 2), round(corr, 2), len(d))
        lim = float(np.abs(d.close3).quantile(0.999)) * 1.15
        ax.scatter(d.close3, d.close10, s=10 if len(d) > 500 else 26, color=C[0], alpha=0.25 if len(d) > 500 else 0.7, lw=0)
        xs = np.array([-lim, lim])
        ax.plot(xs, ratio * xs, color=MUTED, lw=1.5, ls="--", label=f"DV01 비율 {ratio:.2f}")
        ax.plot(xs, beta * xs, color=C[1], lw=2, label=f"회귀 기울기 {beta:.2f}")
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim * 3.6, lim * 3.6)
        ax.set_title(f"{name} (상관 {corr:.2f}, {len(d):,}개)", loc="left", fontsize=10)
        ax.set_xlabel("3년 선물 가격 변화", color=INK, fontsize=9)
        ax.legend(frameon=False, fontsize=9, loc="upper left")
        clean(ax, grid="both")
    axes[0].set_ylabel("10년 선물 가격 변화", color=INK, fontsize=9)
    fig.suptitle("3년 가격이 변동할 때 10년 가격의 변동: 간격이 길수록 DV01 비율(3:1)과 일치", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    save(fig, "fig_hedge_ratio.png")
    return out


def cost_table(sig):
    """README 2절 후보 표와 같은 계산. sig = 9/11~11/09 14:27 봉으로 만든 일별 스프레드"""
    s = sig.spread_bp
    rows = []
    for n in (5, 10, 20):
        m, sd = s.rolling(n).mean().shift(1), s.rolling(n).std().shift(1)
        z = (s - m) / sd
        for k in (1.0, 1.5, 2.0):
            hit = z.abs() >= k
            dist = float((s - m).abs()[hit].median())
            rows.append({"N": n, "k": k, "days": int(hit.sum()), "of": int(z.notna().sum()), "dist": round(dist, 2),
                         "share": COST_BP / dist})
    return pd.DataFrame(rows)


def fig_cost_screen(tab):
    hold = [("당일", 1.01), ("3일", 2.3), ("5일", 3.5), ("10일", 4.63)]  # explore_summary.json, README 2절
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2), width_ratios=[1, 2.1])

    def draw(ax, labels, shares, chosen=None):
        cols = [C[0] if v <= 0.2 else "#c9c8c3" for v in shares]
        bs = ax.bar(labels, np.array(shares) * 100, color=cols, width=0.62)
        for i, (bar, v) in enumerate(zip(bs, shares)):
            ax.annotate(f"{v * 100:.0f}%", (bar.get_x() + bar.get_width() / 2, v * 100), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=9, color=INK,
                        fontweight="bold" if i == chosen else "normal")
            if i == chosen:
                bar.set_edgecolor(INK)
                bar.set_linewidth(1.8)
        ax.axhline(20, color=INK, lw=1, ls="--")
        ax.set_ylim(0, max(shares) * 100 * 1.18)
        clean(ax)

    draw(a1, [h[0] for h in hold], [COST_BP / h[1] for h in hold])
    a1.set_title("보유 기간별 (변동 폭 중앙값 대비)", loc="left", fontsize=10)
    a1.set_ylabel("왕복 비용 0.78bp의 비중 (%)", color=INK, fontsize=9)
    labels = [f"N={r.N}\nk={r.k}\n{r.days}/{r.of}일" for r in tab.itertuples()]
    chosen = int(tab[(tab.N == 10) & (tab.k == 1.5)].index[0])
    draw(a2, labels, list(tab.share), chosen)
    a2.set_title("평균 기간 N, 진입 z값 k 후보별 (진입 시 평균선까지 거리 중앙값 대비). 테두리 = 채택", loc="left", fontsize=10)
    a2.annotate("기준 20%", (8.45, 20), xytext=(0, 4), textcoords="offset points", ha="right", fontsize=9, color=INK)
    a2.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=C[0], label="통과 (20% 이하)"),
                       plt.Rectangle((0, 0), 1, 1, color="#c9c8c3", label="탈락")], frameon=False, fontsize=9, loc="upper right")
    fig.suptitle("비용 기준 선별: 왕복 비용이 기대 변동 폭의 20% 이하인 후보만 통과 (손익을 보기 전에 적용)", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    save(fig, "fig_cost_screen.png")


# ---------- 5절 ----------
def fig_backtest(b, sig):
    bt = b[b.index <= "2026-11-09 14:27"]
    trades, _, _ = backtest.run(bt)
    s = sig.spread_bp
    m, sd = s.rolling(S.N).mean().shift(1), s.rolling(S.N).std().shift(1)
    z = (s - m) / sd
    pos = {d: i for i, d in enumerate(s.index)}
    x = np.arange(len(s))
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 9.2), height_ratios=[2.2, 1.2, 1.1])

    a1.fill_between(x, m - S.K * sd, m + S.K * sd, color="#c9c8c3", alpha=0.35, lw=0, label="평균 ± 1.5 표준편차 (진입 기준)")
    a1.plot(x, m, color=MUTED, lw=1.2, ls="--", label="지난 10거래일 평균")
    a1.plot(x, s, color=INK, lw=1.8, label="15:30 스프레드")
    NUM = "①②③④"
    for i, t in enumerate(trades):
        c = C[0] if t["side"] > 0 else C[1]
        xe = pos[pd.Timestamp(t["entry_t"]).normalize()]
        xd = pos[pd.Timestamp(t["exit_t"]).normalize()]
        frac = 0 if t["reason"] != "손절" else -0.35  # 손절은 장중이라 그날 15:30 점보다 앞에 표시
        a1.plot([xe, xd + frac], [t["entry_spread"], t["exit_spread"]], color=c, lw=2.2, alpha=0.9)
        a1.plot(xe, t["entry_spread"], "^" if t["side"] > 0 else "v", color=c, ms=11, mec="white", mew=1.5)
        a1.plot(xd + frac, t["exit_spread"], "X" if t["reason"] == "손절" else "o", color=c, ms=10, mec="white", mew=1.5)
        off, ha = [((-6, 10), "right"), ((-6, -17), "right"), ((10, -26), "left"), ((10, -3), "left")][i]  # 겹치지 않는 자리
        a1.annotate(f"{NUM[i]} {'스티프닝' if t['side'] > 0 else '플래트닝'} z {t['z']:+.2f}", (xe, t["entry_spread"]),
                    xytext=off, textcoords="offset points", ha=ha, fontsize=9, color=INK)
        stop = t["reason"] == "손절"
        left = stop and i == 1
        a1.annotate(f"{t['reason']} {t['net_krw']:+,}원", (xd + frac, t["exit_spread"]),
                    xytext=(-4 if left else 6, -16 if stop else 9), textcoords="offset points",
                    ha="right" if left else "left", fontsize=9, color=INK)
    end_bt = pos[pd.Timestamp("2026-11-09")]
    for a in (a1, a2):
        a.axvspan(end_bt + 0.5, len(s) - 0.5, color=C[3], alpha=0.10, lw=0)
    a1.annotate("실전\n11/10~13", (end_bt + 0.6, 27), fontsize=9, color=INK, va="bottom")
    a1.set_ylabel("스프레드 (bp)", color=INK)
    a1.legend(frameon=False, fontsize=9, loc="lower left", ncol=3)
    a1.set_title("백테스트 4회 거래: ▲ 스티프닝 진입, ▼ 플래트닝 진입, ● 평균 복귀 청산, X 손절 (손익은 비용 포함)", loc="left", fontsize=11)

    a2.bar(x, z, color=[C[0] if v <= -S.K else C[1] if v >= S.K else "#c9c8c3" for v in z.fillna(0)], width=0.7)
    for k in (S.K, -S.K):
        a2.axhline(k, color=INK, lw=1, ls="--")
    a2.axhline(0, color=MUTED, lw=0.8)
    a2.annotate("+1.5 플래트닝 진입", (0, S.K), xytext=(0, 3), textcoords="offset points", fontsize=9, color=INK)
    a2.annotate("-1.5 스티프닝 진입", (0, -S.K), xytext=(0, -12), textcoords="offset points", fontsize=9, color=INK)
    a2.set_ylabel("z", color=INK)
    a2.set_title("일별 z (분봉 기준. 처음 10일은 평균이 없어 계산하지 않음)", loc="left", fontsize=10)
    step = 4
    for a in (a1, a2):
        a.set_xlim(-0.7, len(s) - 0.3)
        a.set_xticks(x[::step], [d.strftime("%m/%d") for d in s.index[::step]])
        clean(a)

    lab = [f"{NUM[i]} {'스티프닝' if t['side'] > 0 else '플래트닝'}\n{pd.Timestamp(t['entry_t']):%m/%d}~{pd.Timestamp(t['exit_t']):%m/%d}"
           for i, t in enumerate(trades)] + ["합계"]
    gross = [t["pnl_krw"] for t in trades] + [sum(t["pnl_krw"] for t in trades)]
    net = [t["net_krw"] for t in trades] + [sum(t["net_krw"] for t in trades)]
    xx = np.arange(len(lab))
    for off, vals, c, name in ((-0.2, gross, "#c9c8c3", "비용 전"), (0.2, net, C[0], "비용 후 (왕복 67,680원)")):
        bs = a3.bar(xx + off, np.array(vals) / 1e4, width=0.36, color=c, label=name)
        for bar, v in zip(bs, vals):
            a3.annotate(f"{v / 1e4:+.1f}", (bar.get_x() + bar.get_width() / 2, v / 1e4), xytext=(0, 3 if v >= 0 else -3),
                        textcoords="offset points", ha="center", va="bottom" if v >= 0 else "top", fontsize=9, color=INK)
    a3.axhline(0, color=MUTED, lw=0.8)
    a3.axvline(len(trades) - 0.5, color=GRID, lw=1)
    a3.set_xticks(xx, lab)
    a3.set_ylim(min(net) / 1e4 * 1.3, max(gross) / 1e4 * 1.9)
    a3.set_ylabel("손익 (만원)", color=INK)
    a3.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    a3.set_title("거래별 손익 (한 세트 = 3년 3계약 + 10년 1계약)", loc="left", fontsize=10)
    clean(a3)
    fig.tight_layout()
    save(fig, "fig_backtest.png")
    return z


def fig_live_week():
    fig, axes = plt.subplots(1, 5, figsize=(13, 4.4), sharey=True)
    out = []
    for ax, day in zip(axes, LIVE_DAYS):
        recs = live(day)
        tk = pd.DataFrame([{"t": r["t"], "bp": r["spread_bp"]} for r in recs if r["event"] in ("틱", "신호")]).set_index("t")
        sg = next(r for r in recs if r["event"] == "신호")
        fails = [r["t"] for r in recs if r["event"] == "시세 실패"]
        thr = sg["mean"] - S.K * sg["std"]
        gap = tk.index.to_series().diff().dt.total_seconds()
        y = tk.bp.where(~(gap > 150).shift(-1, fill_value=False))  # 2분 30초 넘게 비면 선을 잇지 않는다
        ax.plot(tk.index, tk.bp, color=C[0], lw=1.3)
        ax.axhline(thr, color=INK, lw=1, ls="--")
        ax.axhline(sg["mean"], color=MUTED, lw=1, ls=":")
        if fails:
            ax.plot(fails, [17.4] * len(fails), "|", color=C[1], ms=9, mew=1.5)
        hit = sg["z"] <= -S.K
        ax.plot(sg["t"], sg["spread_bp"], "o", color=C[1] if hit else C[0], ms=9, mec="white", mew=1.5, zorder=5)
        d = pd.Timestamp(day)
        ax.set_xlim(d + pd.Timedelta(hours=8, minutes=40), d + pd.Timedelta(hours=15, minutes=50))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[9, 11, 13, 15]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H시"))
        ax.set_title(f"{d:%m/%d}({WD[d.weekday()]})  틱 {len(tk) - 1}회" + (f", 실패 {len(fails)}회" if fails else ""),
                     loc="left", fontsize=10)
        ax.text(0.04, 0.98, f"10일 평균 {sg['mean']:.2f} (가는 점선)\n진입 기준 {thr:.2f} (굵은 점선)\n"
                f"15:30 스프레드 {sg['spread_bp']:.2f}, z {sg['z']:+.2f}", transform=ax.transAxes, va="top", fontsize=9,
                color=INK, linespacing=1.5)
        ax.text(0.04, 0.80, "→ 스티프닝 진입 신호" if hit else "→ 기준 미달, 주문 없음", transform=ax.transAxes, va="top",
                fontsize=9.5, color=INK, fontweight="bold" if hit else "normal")
        clean(ax)
        gaps = gap.dropna()
        out.append({"day": day, "ticks": len(tk) - 1, "fails": len(fails), "first": f"{tk.index[0]:%H:%M}",
                    "max_gap_s": int(gaps.max()), "lo": float(tk.bp.min()), "hi": float(tk.bp.max()),
                    "z": sg["z"], "sig_bp": sg["spread_bp"], "mean": sg["mean"], "std": sg["std"], "thr": round(thr, 2)})
    axes[0].set_ylabel("스프레드 (bp)", color=INK)
    axes[0].set_ylim(17.1, 27.9)
    fig.suptitle("실전 5일: 1분 스프레드(파란 선)와 그날의 스티프닝 진입 기준(점선 = 10일 평균 - 1.5 표준편차). 아래 주황 눈금 = 시세 조회 실패",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    save(fig, "fig_live_week.png")
    return out


# ---------- 6절 ----------
def fig_order_1112():
    t0 = pd.Timestamp("2026-11-12 15:30:50")
    sec = lambda s: (pd.Timestamp(f"2026-11-12 {s}") - t0).total_seconds()  # noqa: E731
    fig, ax = plt.subplots(figsize=(11, 3.9))
    ax.axhline(0, color=MUTED, lw=1.2)
    ax.axvspan(sec("15:31:00.229"), sec("15:31:30.527"), ymin=0.42, ymax=0.58, color=C[1], alpha=0.25, lw=0)
    ax.annotate("주문내역 상태 「미접수」 30.3초", ((sec("15:31:00.229") + sec("15:31:30.527")) / 2 + 4, 0.02), ha="center",
                va="bottom", fontsize=9, color=INK)
    ev = [("15:30:58", "신호 z -1.733\n스티프닝 진입 판정", 1, C[0], "o"),
          ("15:31:00.229", "10년 매도 1 주문\n응답 HTTP 200 (ord 974)", -1, C[0], "o"),
          ("15:31:08", "프로그램: 잔고 변화 없음\n→ 「첫 다리 실패」로 종료\n3년 주문은 제출하지 않음", 1, C[1], "X"),
          ("15:31:30.527", "거래소 접수, 체결 108.71\n10년 매도 1계약만 보유", -1, C[1], "o")]
    for tm, txt, side, c, mk in ev:
        x = sec(tm)
        ax.plot([x, x], [0, 0.45 * side], color=GRID, lw=1.2, zorder=1)
        ax.plot(x, 0, mk, color=c, ms=11, mec="white", mew=1.5, zorder=3)
        ha = {"15:30:58": "right", "15:31:00.229": "right", "15:31:08": "left"}.get(tm, "center")
        ax.annotate(f"{tm[:8]}\n{txt}", (x + (1 if ha == "right" else -1 if ha == "left" else 0), 0.5 * side), ha=ha,
                    va="bottom" if side > 0 else "top", fontsize=9, color=INK)
    for x in [sec(f"15:31:0{i}") + 0.6 for i in range(1, 6)]:
        ax.plot(x, 0, "|", color=INK, ms=10, mew=1.2, zorder=2)
    ax.annotate("주문내역 조회 5회\n모두 「미접수」", (sec("15:31:03.6") + 3, -0.2), ha="left", va="top", fontsize=8.5, color=MUTED)
    ax.annotate("17:14 잔고 조회로 10년 매도 1계약 확인\n17:20:22 시장가 매수 1로 청산, 체결 108.72\n가격 손익 -10,000원 (수수료 별도)",
                (sec("15:31:44"), 0.5), ha="left", va="bottom", fontsize=9, color=INK)
    ax.annotate("", (sec("15:31:43"), 0), (sec("15:31:33"), 0), arrowprops={"arrowstyle": "->", "color": MUTED})
    ax.set_xlim(-12, 76)
    ax.set_ylim(-1.15, 1.3)
    ticks = [sec("15:30:50") + 10 * i for i in range(6)]
    ax.set_xticks(ticks, [(t0 + pd.Timedelta(seconds=s)).strftime("%H:%M:%S") for s in ticks])
    ax.set_yticks([])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=9)
    ax.set_title("11/12 진입 주문 경과: 주문 응답 30초 뒤에 접수되어, 프로그램 종료 후 한쪽 다리만 체결", loc="left", fontsize=11)
    fig.tight_layout()
    save(fig, "fig_order_1112.png")


# ---------- 7절 ----------
KINDS = [("정상 응답", "#c9c8c3"), ("401 EGW023", C[0]), ("401 EGW052", C[3]), ("403 EGW016", C[4]),
         ("연결 오류 WinError 10014", C[1]), ("응답 지연, 기타 연결 오류", C[2])]


def api_counts():
    rows = {}
    for day in LIVE_DAYS:
        c = Counter()
        for p in sorted((RESULTS / "api_log").glob(f"{day}*.jsonl")):
            for line in open(p, encoding="utf-8"):
                r = json.loads(line)
                txt = json.dumps(r.get("response"), ensure_ascii=False)
                if r["status"] == 200:
                    k = "정상 응답"
                elif "EGW023" in txt or "EGW052" in txt or "EGW016" in txt:
                    k = f"{r['status']} " + next(e for e in ("EGW023", "EGW052", "EGW016") if e in txt)
                elif "10014" in txt:
                    k = "연결 오류 WinError 10014"
                else:
                    k = "응답 지연, 기타 연결 오류"
                c[k] += 1
        rows[day] = c
    return pd.DataFrame(rows).T.reindex(columns=[k for k, _ in KINDS]).fillna(0).astype(int)


def fig_api_health(df):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.3), width_ratios=[1, 1.5])
    labels = [f"{pd.Timestamp(d):%m/%d}({WD[pd.Timestamp(d).weekday()]})" for d in df.index]
    tot = df.sum(axis=1)
    a1.bar(labels, tot, color="#c9c8c3", width=0.6)
    for i, (t, ok) in enumerate(zip(tot, df["정상 응답"])):
        a1.annotate(f"{t:,}회\n정상 {ok / t * 100:.1f}%", (i, t), xytext=(0, 3), textcoords="offset points", ha="center",
                    fontsize=9, color=INK)
    a1.set_ylim(0, tot.max() * 1.2)
    a1.set_title("일별 API 호출 수 (재시도 포함)", loc="left", fontsize=10)
    clean(a1)
    bottom = np.zeros(len(df))
    for k, c in KINDS[1:]:
        a2.bar(labels, df[k], bottom=bottom, color=c, width=0.6, label=k, edgecolor="white", linewidth=1.5)
        for i, v in enumerate(df[k]):
            if v >= 20:
                a2.annotate(f"{v}", (i, bottom[i] + v / 2), ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        bottom += df[k].values
    for i, v in enumerate(bottom):
        a2.annotate(f"{int(v)}", (i, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9, color=INK)
    a2.set_ylim(0, bottom.max() * 1.15)
    a2.legend(frameon=False, fontsize=9, loc="upper left")
    a2.set_title("오류 응답 수 (종류별)", loc="left", fontsize=10)
    clean(a2)
    fig.suptitle("일별 API 호출과 오류: 11/09~10은 토큰 오류, 11/12~13은 실행용 PC의 연결 오류", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    save(fig, "fig_api_health.png")


def main():
    b = all_bars()
    sig = signal_rows(b)
    fig_spread_level(sig)
    print("기울기(기울기, 상관, 개수):", fig_hedge_ratio(b[b.index <= "2026-11-09 14:27"]))
    tab = cost_table(signal_rows(b[b.index <= "2026-11-09 14:27"]))
    print(tab.round(3).to_string(index=False))
    fig_cost_screen(tab)
    z = fig_backtest(b, sig)
    print(pd.DataFrame({"bp": sig.spread_bp, "z": z}).tail(8).round(3))
    print(pd.DataFrame(fig_live_week()).to_string(index=False))
    fig_order_1112()
    df = api_counts()
    print(df.to_string())
    fig_api_health(df)


if __name__ == "__main__":
    main()
