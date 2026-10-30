# 누적 손익 차트 2장 + 당일 봉 대기 규칙 전후 비교(10/26~10/30 백테스트)
#   results/cum_candidates.png   후보 비교 (backtest_trades.csv, 수수료 0원 — 2절 표와 같은 가정)
#   results/cum_rule_change.png  B 규칙 변경 전후, 9/11~10/30 백테스트(수수료 2,400원) + 10/26~10/30 실전
import json

import matplotlib.pyplot as plt
import pandas as pd

import backtest
from fetch_bars import BARS_1M, BARS_5M, RESULTS, SYM, load
from strategy import WARMUP, bollinger

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
INK, MUTED, GRID = "#52514e", "#8a8984", "#e6e5e1"
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]  # dataviz 기본 범주 팔레트 1~5번
FEE = 2400  # 왕복 수수료 실측 (README 5절 수동 왕복 점검)
WEEK_1M = RESULTS / f"bars_{SYM}_1m_20261026_20261030.json"
WEEK_5M = RESULTS / f"bars_{SYM}_5m_20261026_20261030.json"


def live_trades():
    rows = []
    for d in pd.bdate_range("2026-10-26", "2026-10-30"):
        for line in open(RESULTS / f"journal_{d:%Y%m%d}.jsonl", encoding="utf-8"):
            e = json.loads(line)
            if e["event"] == "exit":
                rows.append({"exit_t": pd.Timestamp(e["ts"]), "krw": e["pnl"]})
    return pd.DataFrame(rows)


def step(ax, tr, color, label, end_label=True, **kw):
    """거래 청산 시점마다 누적 손익이 계단처럼 바뀌는 선 + 끝에 이름 직접 표시"""
    t = pd.concat([pd.Series([tr.exit_t.iloc[0].normalize()]), tr.exit_t])
    y = pd.concat([pd.Series([0]), tr.krw.cumsum()]) / 10_000
    ax.step(t, y.values, where="post", color=color, lw=2, label=label, **kw)
    if end_label:
        ax.annotate(f"{label} {y.iloc[-1] * 10_000:+,.0f}원", (t.iloc[-1], y.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK)


def style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, color="#0b0b0b")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_ylabel("누적 손익 (만원)", color=INK)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=INK)


def main():
    # 1) 이번 주 백테스트: 같은 1분봉·5분봉에 진입 제외 조건만 바꿔 돌린다
    b1 = load(WEEK_1M, 1)
    b5 = pd.concat([load(BARS_5M[1], 5), load(WEEK_5M, 5)]).sort_index()  # 10/26 아침 밴드에 10/23 봉 필요
    b5 = b5[~b5.index.duplicated()]
    rules = {"변경 전 (하루 첫 봉만 제외)": 1, f"변경 후 (당일 봉 {WARMUP}개 대기)": WARMUP}
    week = {}
    for fee in (0, FEE):
        backtest.FEE_KRW = fee
        for name, w in rules.items():
            tr = backtest.run(b1, bollinger(b5, warmup=w))
            week[(name, fee)] = tr
            day = tr.groupby(tr.day.dt.strftime("%m/%d")).krw.sum().to_dict()
            print(f"수수료 {fee:>5,}원 | {name}: {len(tr)}회, 승률 {(tr.krw > 0).mean():.0%}, "
                  f"{tr.krw.sum():+,}원, 손절 {(tr.reason == '손절').sum()}회 | 일별 {day}")
    for name in rules:
        tr = week[(name, FEE)]
        print(f"\n{name} 거래 (수수료 {FEE:,}원)")
        print(tr[["entry_t", "side", "entry_px", "exit_t", "exit_px", "reason", "krw"]].to_string(index=False))

    # 2) 9/11~10/23 백테스트도 같은 수수료로 (README 6절 7번 표와 같은 값이 나와야 한다)
    b1_all = pd.concat([load(BARS_1M, 1), b1]).sort_index()
    b5_all = pd.concat([load(p, 5) for p in BARS_5M] + [load(WEEK_5M, 5)]).sort_index()
    b5_all = b5_all[~b5_all.index.duplicated()]
    backtest.FEE_KRW = FEE
    full = {name: backtest.run(b1_all, bollinger(b5_all, warmup=w)) for name, w in rules.items()}

    # 차트 1: 후보 비교
    cand = pd.read_csv(RESULTS / "backtest_trades.csv", parse_dates=["exit_t"])
    fig, ax = plt.subplots(figsize=(11, 5))
    for color, (name, tr) in zip(C, cand.groupby("cand", sort=False)):
        step(ax, tr.reset_index(drop=True), color, f"{name} {tr.krw.sum():+,}원", end_label=False)  # 끝 이름이 겹쳐 범례로
    ax.axvline(pd.Timestamp("2026-10-10"), color=MUTED, lw=1, ls=(0, (4, 3)))
    ax.text(pd.Timestamp("2026-10-09"), ax.get_ylim()[1], "선택 구간 ← | → 검증 구간 ",
            ha="center", va="top", fontsize=9, color=MUTED,
            bbox=dict(fc="white", ec="none", pad=1))
    style(ax, "후보 전략 누적 손익 (백테스트, 1계약, 1틱 슬리피지, 수수료 0원)")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m/%d"))
    fig.tight_layout()
    fig.savefig(RESULTS / "cum_candidates.png", dpi=130)

    # 차트 2: 규칙 변경 전후
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw={"width_ratios": [2, 1.2]})
    for color, (name, tr) in zip(C, full.items()):
        step(a1, tr, color, name.split(" (")[0])
    a1.axvspan(pd.Timestamp("2026-10-26"), pd.Timestamp("2026-10-31"), color="#f3f2ee", lw=0, zorder=0)
    a1.set_xlim(right=pd.Timestamp("2026-11-12"))
    a1.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m/%d"))
    style(a1, f"B 백테스트 9/11~10/30 (수수료 {FEE:,}원)")
    a1.legend(loc="lower left", frameon=False, fontsize=9)

    for color, name in zip(C, rules):
        step(a2, week[(name, FEE)], color, "백테스트 " + name.split(" (")[0])
    step(a2, live_trades(), INK, "실전", ls=(0, (2, 1.5)))
    a2.set_xlim(pd.Timestamp("2026-10-26"), pd.Timestamp("2026-11-02"))
    a2.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m/%d"))
    style(a2, "10/26~10/30 (실전은 10/29부터 변경 후 규칙)")
    a2.legend(loc="lower left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(RESULTS / "cum_rule_change.png", dpi=130)
    print("\n저장: results/cum_candidates.png, results/cum_rule_change.png")


if __name__ == "__main__":
    main()
