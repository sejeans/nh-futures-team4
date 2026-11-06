# README 3절(매매 로직) 설명용 그림 3개. 실전 신호와 같은 함수(daily, roll_days, adjust, tsmom)로 계산한다.
# 입력: results/bars_ZN_cont_1d_20261106_0810.json (11/06 08:10 자동 실행이 받은 연결 일봉)
# 출력: results/logic_today.png, logic_history.png, logic_roll.png
import matplotlib.pyplot as plt
import pandas as pd

from strategies import adjust, daily, roll_days, tsmom  # 먼저: nh_os 가 week02 를 sys.path 앞에 넣는다
from fetch_bars import RESULTS
from nh_os import SPEC
from plot_strategies import GRID, INK, MUTED, SURFACE

BUY, SELL = "#2a78d6", "#eb6834"  # 매수 / 매도 (plot_strategies 와 같은 색, 색각 검증 통과)
SRC = RESULTS / "bars_ZN_cont_1d_20261106_0810.json"
TICK = SPEC["ZN"]["tick"]
plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(RESULTS / name, dpi=130, facecolor=SURFACE)
    print("저장:", RESULTS / name)


def today(c):
    """그림 1: 11/06 신호. 어제 종가와 252거래일 전 종가 두 점만 비교한다"""
    now, ago = c.index[-1], c.index[-253]
    w = c[ago - pd.Timedelta(days=20):]
    fig, ax = plt.subplots(figsize=(10, 4.2), facecolor=SURFACE)
    style(ax)
    ax.plot(w.index, w.values, color=MUTED, lw=1.2)
    ax.axhline(c[ago], color=SELL, lw=1, ls="--")
    for t, txt, off, ha in ((ago, "①", (0, -22), "center"), (now, "②", (10, -4), "left")):
        ax.plot(t, c[t], "o", ms=9, color=INK, mec=SURFACE, mew=2, zorder=3)
        ax.annotate(txt, (t, c[t]), xytext=off, textcoords="offset points", ha=ha, fontsize=11, color=INK)
    ax.annotate("", (now, c[now]), xytext=(now, c[ago]), arrowprops=dict(arrowstyle="->", color=SELL, lw=2))
    diff = c[now] - c[ago]
    ax.text(now - pd.Timedelta(days=8), (c[now] + c[ago]) / 2,
            f"① 252거래일 전 {ago:%Y-%m-%d} 종가 {c[ago]}\n② 어제 {now:%Y-%m-%d} 종가 {c[now]}\n② - ① = {diff:+}포인트 ({diff / TICK:+.0f}틱)\n"
            "→ 1년 전보다 낮음 → 목표 -1 (매도)", ha="right", va="center", fontsize=10, color=INK, linespacing=1.6)
    ax.set_ylabel("가격 (포인트)", color=MUTED, fontsize=9)
    ax.set_title("11/06 08:10 신호: 어제 종가와 252거래일 전 종가를 비교", loc="left", fontsize=11, color=INK)
    ax.set_xlim(right=now + pd.Timedelta(days=20))
    ax.set_ylim(bottom=w.min() - 1.2)
    save(fig, "logic_today.png")


def history(c, s):
    """그림 2: 2024-01부터 신호. 위: 가격과 252거래일 전 가격, 아래: 목표 포지션"""
    prev = c.shift(252)
    k = s[s.index >= "2024-01-03"].index  # 252거래일이 쌓인 첫날
    c, prev, s = c[k], prev[k], s[k]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 5.6), sharex=True, height_ratios=[3, 1], facecolor=SURFACE)
    for ax in (a1, a2):
        style(ax)
    a1.plot(c.index, c.values, color=INK, lw=1.5, label="어제 종가")
    a1.plot(prev.index, prev.values, color=MUTED, lw=1.2, ls="--", label="252거래일 전 종가")
    a1.fill_between(c.index, c, prev, where=c > prev, color=BUY, alpha=0.18, lw=0, label="위에 있음 → 매수")
    a1.fill_between(c.index, c, prev, where=c < prev, color=SELL, alpha=0.18, lw=0, label="아래에 있음 → 매도")
    a1.set_ylabel("가격 (포인트, 교체 조정)", color=MUTED, fontsize=9)
    a1.set_ylim(top=c.max() + 6)  # 범례 자리
    a1.legend(loc="upper left", fontsize=8, frameon=False, ncol=4)
    a1.set_title("ZN TSMOM 12개월 신호, 2024-01-03 ~ 2026-11-05", loc="left", fontsize=11, color=INK)

    a2.fill_between(s.index, 0, s.where(s > 0, 0), step="post", color=BUY, lw=0)
    a2.fill_between(s.index, 0, s.where(s < 0, 0), step="post", color=SELL, lw=0)
    a2.set_yticks([-1, 0, 1], ["매도 -1", "0", "매수 +1"])
    a2.set_ylabel("목표 포지션", color=MUTED, fontsize=9)

    flips = s[(s != s.shift()) & (s.index >= "2026-03-01") & (s.index <= "2026-05-31")]
    a2.annotate(f"2026년 3~5월 {len(flips)}번 바뀜\n(가격이 1년 전 수준 근처)", (flips.index[len(flips) // 2], 1),
                xytext=(-150, 4), textcoords="offset points", fontsize=8, color=INK,
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=1))
    live = pd.Timestamp("2026-11-05")
    a1.annotate("11/05 실전 매도\n106.9375", (live, 106.9375), xytext=(-80, 30), textcoords="offset points", fontsize=8,
                color=INK, arrowprops=dict(arrowstyle="->", color=MUTED, lw=1))
    a1.plot(live, 106.9375, "o", ms=8, color=SELL, mec=SURFACE, mew=2, zorder=3)
    save(fig, "logic_history.png")
    print("3~5월 신호 변경:", [f"{t:%m/%d}" for t in flips.index])
    print("마지막 변경:", f"{s[s != s.shift()].index[-1]:%Y-%m-%d}", int(s.iloc[-1]))


def roll(d, a, rolls):
    """그림 3: 8/28 월물 교체. 원가격은 교체일에 계단이 생기고, 조정 가격은 이전 가격을 옮겨 계단을 없앤다"""
    t = rolls[-1]
    w = slice(t - pd.Timedelta(days=14), t + pd.Timedelta(days=10))
    raw, adj = d.close[w], a.close[w]
    gap = d.open[t] - d.close.shift()[t]
    fig, ax = plt.subplots(figsize=(10, 4), facecolor=SURFACE)
    style(ax)
    ax.plot(raw.index, raw.values, color=MUTED, lw=1.5, marker="o", ms=4, label="API 원가격 (9월물 → 12월물이 이어 붙음)")
    ax.plot(adj.index, adj.values, color=BUY, lw=2, marker="o", ms=4, label="조정 가격 (교체 전 가격에 차이를 더함)")
    ax.axvline(t, color=GRID, lw=6, zorder=0)
    ax.text(t, ax.get_ylim()[1], f" 교체일 {t:%m/%d}\n 시가 - 전날 종가 = {gap:+.6g} ({gap / TICK:+.0f}틱)",
            va="top", fontsize=9, color=INK)
    ax.set_ylabel("종가 (포인트)", color=MUTED, fontsize=9)
    ax.set_title("월물 교체 조정: 교체로 생긴 가격 차이는 신호 계산에서 뺀다", loc="left", fontsize=11, color=INK)
    ax.legend(loc="lower left", fontsize=8, frameon=False)
    save(fig, "logic_roll.png")
    print(f"교체일 {t:%Y-%m-%d} 갭 {gap:+.6f} = {gap / TICK:+.1f}틱")


def main():
    d = daily("ZN", SRC, until="2026-11-06")  # trend_live 와 같은 조건: 실행일(11/06) 봉 제외
    rolls = roll_days(d, TICK)
    a = adjust(d, rolls)
    c = a.close
    s = tsmom(c)
    assert int(s.iloc[-1]) == -1 and round(c.iloc[-1], 6) == 107.328125 and round(c.iloc[-253], 6) == 113.5  # trend_live_20261106_081003.json 과 같은 값
    print(f"252거래일 전 원가격 {d.close.iloc[-253]} / 조정 {c.iloc[-253]} / 그 뒤 교체일 {[f'{x:%m/%d}' for x in rolls if x > c.index[-253]]}")
    today(c)
    history(c, s)
    roll(d, a, rolls)


if __name__ == "__main__":
    main()
