# 전략별 누적 손익 차트 (strategies.py 결과 strategies_daily_usd.csv) → results/strategies_equity.png
import matplotlib.pyplot as plt
import pandas as pd

from fetch_bars import RESULTS

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
PANELS = [
    ("추세추종 (ZN 1계약)", {"보유_매수(비교용)": ("#9a9893", "보유 매수 (비교)"),
                         "추세_TSMOM_12개월": ("#2a78d6", "TSMOM 일별 (실전)"),
                         "추세_TSMOM_12개월_월간": ("#eb6834", "TSMOM 월간"),
                         "추세_이동평균_50_200": ("#1baf7a", "이동평균 50/200"),
                         "추세_돈치안_20_10": ("#eda100", "돈치안 20/10")}),
    ("커브 스프레드 (+3 ZF, -2 ZN)", {"커브_스프레드추세_20일": ("#e87ba4", "스프레드 추세 20일"),
                                 "커브_스프레드회귀_z2": ("#008300", "스프레드 회귀 z±2")}),
]


def main():
    d = pd.read_csv(RESULTS / "strategies_daily_usd.csv", index_col=0, parse_dates=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), facecolor=SURFACE)
    for ax, (title, series) in zip(axes, PANELS):
        ax.set_facecolor(SURFACE)
        ends = []
        for col, (color, label) in series.items():
            eq = d[col].dropna().cumsum()
            ax.plot(eq.index, eq.values, color=color, lw=2 if "실전" in label else 1.5, label=label)
            ends.append([eq.iloc[-1], eq.index[-1], f"{label} {eq.iloc[-1]:+,.0f}"])
        lo, hi = ax.get_ylim()
        gap = (hi - lo) * 0.045  # 이름표 줄 간격: 끝값이 가까운 선끼리 겹치지 않게 아래로 민다
        ends.sort(reverse=True)
        for prev, cur in zip(ends, ends[1:]):
            cur.append(min(cur[0], (prev[3] if len(prev) > 3 else prev[0]) - gap))
        for e in ends:
            ax.annotate(e[2], (e[1], e[0]), xytext=(e[1] + pd.Timedelta(days=15), e[3] if len(e) > 3 else e[0]), textcoords="data",
                        va="center", fontsize=8, color=INK)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_ylabel("누적 손익 (USD, 비용 포함)", color=MUTED, fontsize=9)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.legend(loc="lower left", fontsize=8, frameon=False)
        ax.set_xlim(right=d.index[-1] + pd.Timedelta(days=330))  # 오른쪽 이름표 자리
    fig.suptitle("2023-01-12 ~ 2026-11-04 백테스트, 다음 날 시가 체결, 편도 1틱 + $8", x=0.01, ha="left",
                 fontsize=9, color=MUTED)
    fig.tight_layout()
    out = RESULTS / "strategies_equity.png"
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    print("저장:", out)


if __name__ == "__main__":
    main()
