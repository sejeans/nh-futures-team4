# 6주차 README 차트 (저장된 results/ 파일만 사용, API 호출 없음)
#   results/fig_bt_scenarios.png   위험관리 규칙을 하나씩 더한 백테스트 6개 시나리오, 구간별 손익 (bt_summary.json)
#   results/fig_live_YYYYMMDD.png  실전 하루: 1분봉 종가, 5분봉 볼린저 밴드, 진입/청산/손절가 (journal_*.jsonl)
#                                  그날 1분봉, 5분봉이 필요하다: python data06.py YYYY-MM-DD YYYY-MM-DD
# 사용: python plot06.py             차트 전부 (실전은 journal 이 있는 모든 날)
#       python plot06.py 20261123    실전 하루만
import json
import sys

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from data06 import RESULTS, load

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
INK, MUTED, GRID = "#52514e", "#8a8984", "#e6e5e1"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b"  # 5주차 plot_analysis.py 와 같은 팔레트


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
    fig.savefig(RESULTS / name, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("저장:", name)


def bt_scenarios():
    rows = json.loads((RESULTS / "bt_summary.json").read_text(encoding="utf-8"))["rows"]
    df = pd.DataFrame(rows)
    names = list(dict.fromkeys(df["시나리오"]))
    pers = list(dict.fromkeys(df["구간"]))
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    h = 0.36
    for j, (per, color) in enumerate(zip(pers, (BLUE, ORANGE))):
        for i, name in enumerate(names):
            v = df[(df["시나리오"] == name) & (df["구간"] == per)]["손익"].iloc[0] / 10_000
            y = i + (j - 0.5) * h
            ax.barh(y, v, height=h - 0.04, color=color, label=per if i == 0 else None)
            ax.text(v + (3 if v >= 0 else -3), y, f"{v:+,.0f}", va="center", ha="left" if v >= 0 else "right",
                    fontsize=8.5, color=INK)
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_yticks(range(len(names)), names, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("손익 (만원, 수수료와 슬리피지 차감)", color=INK, fontsize=9)
    ax.set_xlim(-135, 60)
    clean(ax, "x")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.set_title("위험관리 규칙을 하나씩 더한 백테스트 (코스닥150 선물, 2주차 볼린저 전략)", color=INK, fontsize=10.5,
                 loc="left")
    save(fig, "fig_bt_scenarios.png")


def live_day(day):
    recs = [json.loads(x) for x in (RESULTS / f"journal_{day}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    d = pd.Timestamp(day)
    b1, b5 = load(1), load(5)
    b1 = b1[(b1.day == d) & ~b1.auction]
    if b1.empty:
        print(f"{day} 1분봉 없음. python data06.py {d:%Y-%m-%d} {d:%Y-%m-%d} 먼저 실행")
        return
    n, k = 20, 2  # 2주차 strategy.py 밴드와 같은 값 (20개, 2배, 모표준편차)
    mid = b5.close.rolling(n).mean()
    sd = b5.close.rolling(n).std(ddof=0)
    band = pd.DataFrame({"t": b5.close_t.values, "mid": mid.values, "up": (mid + k * sd).values,
                         "lo": (mid - k * sd).values})
    band = band[band.t.dt.normalize() == d]

    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.fill_between(band.t, band.lo, band.up, step="post", color=BLUE, alpha=0.08, lw=0)
    ax.step(band.t, band.mid, where="post", color=BLUE, lw=1, alpha=0.7, label="중심선 (5분봉 20개 평균)")
    ax.step(band.t, band.up, where="post", color=BLUE, lw=0.8, alpha=0.4, ls="--", label="밴드 ±2 표준편차")
    ax.step(band.t, band.lo, where="post", color=BLUE, lw=0.8, alpha=0.4, ls="--")
    ax.plot(b1.close_t, b1.close, color=INK, lw=1.1, label="1분봉 종가")

    def ts(r):
        return pd.Timestamp(r["ts"])

    enters = [r for r in recs if r["event"] == "enter"]
    exits = [r for r in recs if r["event"] == "exit"]
    for e in enters:  # 손절가: 진입부터 그 거래가 끝날 때까지
        tid = f"{ts(e):%m%d %H:%M}"
        xs = [x for x in exits if x["trade"] == tid]
        end = ts(xs[-1]) if xs else b1.close_t.iloc[-1]
        moved = [r for r in recs if r["event"] == "stop_moved" and r["trade"] == tid]
        t_move = ts(moved[0]) if moved else end
        ax.plot([ts(e), t_move], [e["stop"]] * 2, color=RED, lw=1, ls=":")
        if moved:
            ax.plot([t_move, end], [moved[0]["stop"]] * 2, color=RED, lw=1, ls=":")
        c = AQUA if e["side"] > 0 else ORANGE
        ax.scatter(ts(e), e["px"], marker="^" if e["side"] > 0 else "v", s=90, color=c, zorder=5,
                   edgecolor="white", lw=1.2)
    labels = [(ts(e), e["px"], f"{'매수' if e['side'] > 0 else '매도'} {e['lots']}계약\n{e['px']:.1f}",
               -1 if e["side"] > 0 else 1) for e in enters]
    for x in exits:
        ax.scatter(ts(x), x["exit"], marker="o", s=55, color="white", edgecolor=RED if x["pnl"] < 0 else INK,
                   lw=1.6, zorder=5)
        labels.append((ts(x), x["exit"], f"{x['reason']} {x['lots']}\n{x['pnl'] / 10_000:+.1f}만",
                       1 if x["side"] > 0 else -1))
    placed = []  # (시각, 라벨 높이). 15분, 6포인트 안에 다른 라벨이 있으면 한 칸 더 위(또는 아래)로 올린다
    for t, y, text, where in sorted(labels, key=lambda v: v[0]):
        tier = 0
        while any(abs((t - t0).total_seconds()) < 900 and abs(y + where * 4 * tier - y0) < 6 for t0, y0 in placed):
            tier += 1
        placed.append((t, y + where * 4 * tier))
        dy = (10 if where > 0 else -26) + where * 26 * tier
        ax.annotate(text, (t, y), xytext=(0, dy), textcoords="offset points", ha="center", fontsize=8, color=INK,
                    arrowprops={"arrowstyle": "-", "color": GRID, "lw": 0.8} if tier else None)
    ax.plot([], [], color=RED, lw=1, ls=":", label="손절가 (분할 청산 뒤 진입가로 이동)")
    for r in recs:
        if r["event"] in ("start",) and ts(r).strftime("%H:%M") > "09:00":
            ax.axvline(ts(r), color=MUTED, lw=0.8, ls="--")
            ax.text(ts(r), ax.get_ylim()[0], " 재실행", fontsize=8, color=MUTED, va="bottom")
    end = [r for r in recs if r["event"] == "end"]
    total = end[-1]["pnl_today"] if end else sum(x["pnl"] for x in exits)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlim(pd.Timestamp(f"{day} 08:45"), pd.Timestamp(f"{day} 15:35"))
    clean(ax)
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0, -0.08), ncol=4)
    ax.set_title(f"{d:%m/%d} 실전 (모의계좌, A066C000)  당일 손익 {total:+,}원 (수수료 추정치 차감)", color=INK,
                 fontsize=10.5, loc="left")
    save(fig, f"fig_live_{day}.png")


if __name__ == "__main__":
    days = [a for a in sys.argv[1:] if a.isdigit()]
    if not days:
        bt_scenarios()
        days = sorted(p.stem.split("_")[1] for p in RESULTS.glob("journal_*.jsonl") if "_dry" not in p.stem)
    for day in days:
        live_day(day)
