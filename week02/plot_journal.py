# 실전 저널(journal_YYYYMMDD.jsonl) + 5분봉 볼린저 밴드 → 날짜별 매매 로직 차트 PNG
# 사용: python plot_journal.py 20261026 20261027   (장 마감 후 실행)
# 5분봉 저장본에 그날이 없으면 chart-minute 로 받아 results/ 에 저장한다 (시세 조회만, 주문 없음)
import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from fetch_bars import RESULTS, SYM, chart_client, load
from strategy import MULT, P, TICK, WARMUP, bollinger

ENTRY_UNTIL = P["entry_window_close_time"][1]
LOSS_LIMIT = P["daily_loss_limit_krw"]
SIDE = {1: ("매수", "#2a78d6", "^"), -1: ("매도", "#eb6834", "v")}
INK, MUTED, BAND = "#52514e", "#8a8984", "#c9c8c3"
NUM = "①②③④⑤⑥⑦⑧⑨⑩"
plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})


def bars5(days):
    """5분봉 저장본 전부 + 없으면 요청 구간을 받아 저장. 전일 봉이 있어야 첫 봉부터 밴드가 이어진다"""
    files = sorted(RESULTS.glob(f"bars_{SYM}_5m_*.json"))
    b5 = pd.concat([load(f, 5) for f in files]).sort_index()
    if not set(pd.to_datetime(days)) <= set(b5.day):
        # ponytail: 장중에 받으면 그날 봉이 덜 찬 채 저장된다. 그 파일을 지우고 다시 실행
        out = RESULTS / f"bars_{SYM}_5m_{days[0]}_{days[-1]}.json"
        rec = chart_client()(dcnt="5", inq_strt_dt=days[0], inq_ed_dt=days[-1])
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        b5 = pd.concat([b5, load(out, 5)]).sort_index()
    b5 = b5[~b5.index.duplicated(keep="last")]
    # strategy.bollinger 와 같은 식. 아래 assert 로 신호가 같은지 확인한다
    n, k, ddof = P["bollinger"]["n"], P["bollinger"]["k"], P["bollinger"]["std_ddof"]
    b5["mid"] = b5.close.rolling(n).mean()
    sd = b5.close.rolling(n).std(ddof=ddof)
    b5["up"], b5["lo"] = b5.mid + k * sd, b5.mid - k * sd
    b5["entry"] = bollinger(b5).entry.values
    b5["raw"] = bollinger(b5, warmup=1).entry.values  # 당일 봉 대기 조건이 없었다면 나왔을 신호
    b5 = b5.set_index("close_t")
    return b5


def load_journal(day):
    recs = [json.loads(line) for line in (RESULTS / f"journal_{day}.jsonl").open(encoding="utf-8")]
    for r in recs:
        r["ts"] = datetime.fromisoformat(r["ts"])
    ticks = {r["hm"]: r for r in recs if r["event"] == "tick"}
    trades = list(zip([r for r in recs if r["event"] == "enter"], [r for r in recs if r["event"] == "exit"]))
    start = next(r for r in recs if r["event"] == "start")
    return ticks, trades, start


def explain(b5, b, ticks, trades, start):
    """거래별 진입·청산 근거 문장, 진입하지 않은 신호의 사유. b5 = 전체 5분봉(직전 봉 조회용), b = 그날 봉"""
    lines, taken = [], set()
    for i, (en, ex) in enumerate(trades):
        side = en["side"]
        name = SIDE[side][0]
        t = en["ts"].replace(second=0)
        taken.add(t)
        cur, prev = b5.loc[t], b5.loc[:t].iloc[-2]
        band, op = ("lo", ("<", "≥")) if side > 0 else ("up", (">", "≤"))
        lines.append(f"{NUM[i]} {t:%H:%M} {name} 진입: 직전 종가 {prev.close:.1f} {op[0]} {'하단' if side > 0 else '상단'} "
                     f"{prev[band]:.3f} (밴드 밖) → 이번 종가 {cur.close:.1f} {op[1]} {cur[band]:.3f} (밴드 안 복귀)")
        xt = ex["ts"].replace(second=0)
        moved = round((ex["exit"] - en["entry"]) * side / TICK)
        if ex["reason"] == "중심선":
            row = b.loc[xt]
            why = f"5분봉 종가 {row.close:.1f} {'≥' if side > 0 else '≤'} 중심선 {row.mid:.2f}"
        elif ex["reason"] == "손절":
            px = ticks[f"{xt:%H:%M}"]["px"]
            why = (f"현재가 {px:.1f}, 진입가 대비 {round((px - en['entry']) * side / TICK):+d}틱 "
                   f"(손절선 77틱 = {en['entry'] - side * 77 * TICK:.1f})")
        else:
            why = ex["reason"]
        lines.append(f"     {xt:%H:%M} {ex['reason']} 청산: {why} → 체결 {ex['exit']:.1f}, {moved:+d}틱, {ex['pnl']:+,}원")
    skipped = []
    for t, row in b[b.entry != 0].iterrows():
        if t in taken:
            continue
        tick = ticks.get(f"{t:%H:%M}")
        why = ("진입 시간(~15:25) 이후" if f"{t:%H:%M}" >= ENTRY_UNTIL else
               f"프로그램 실행 전 (시작 {start['ts']:%H:%M})" if tick is None else
               "포지션 보유 중" if tick["pos"] else
               f"일일 손실 한도 도달 (당일 {tick['pnl_today']:+,}원)" if tick["pnl_today"] <= -LOSS_LIMIT else "확인 필요")
        skipped.append((t, int(row.entry), why))
        lines.append(f"△ {t:%H:%M} {SIDE[int(row.entry)][0]} 신호 미진입: {why}")
    return lines, skipped


def day_bars(b5, day):
    d = pd.Timestamp(day)
    return b5[(b5.index > d + pd.Timedelta(hours=9)) & (b5.index <= d + pd.Timedelta(hours=15, minutes=35))]


def plot_day(ax, tx, day, b5):
    ticks, trades, start = load_journal(day)
    d = pd.Timestamp(day)
    b = day_bars(b5, day)
    assert {t.replace(second=0) for t in (en["ts"] for en, _ in trades)} <= set(b.index[b.entry != 0]), "저널 진입이 신호와 다르다"
    lines, skipped = explain(b5, b, ticks, trades, start)

    ax.fill_between(b.index, b.lo, b.up, color=BAND, alpha=0.25, lw=0, step=None)
    ax.plot(b.index, b.up, color=BAND, lw=1)
    ax.plot(b.index, b.lo, color=BAND, lw=1)
    ax.plot(b.index, b.mid, color=MUTED, lw=1, ls=(0, (4, 3)))
    tk = sorted(ticks.values(), key=lambda r: r["ts"])
    ax.plot([datetime.strptime(f"{day} {r['hm']}", "%Y%m%d %H:%M") for r in tk], [r["px"] for r in tk],
            color="#b9b8b3", lw=0.8)
    ax.plot(b.index, b.close, color=INK, lw=1.2, marker="o", ms=2.5)
    if start["ts"] > d + pd.Timedelta(hours=9):
        ax.axvspan(d + pd.Timedelta(hours=9), start["ts"], color="#f3f2ee", lw=0, zorder=0)
        ax.text(d + pd.Timedelta(hours=9, minutes=5), 0.04, "프로그램 실행 전", transform=ax.get_xaxis_transform(),
                fontsize=8.5, color=MUTED)

    for i, (en, ex) in enumerate(trades):
        name, color, mk = SIDE[en["side"]]
        ax.hlines(en["entry"] - en["side"] * 77 * TICK, en["ts"], ex["ts"], color=color, lw=1, ls=(0, (3, 2)))
        ax.plot([en["ts"], ex["ts"]], [en["entry"], ex["exit"]], color=color, lw=2, zorder=3)
        ax.scatter(en["ts"], en["entry"], marker=mk, s=110, color=color, edgecolor="white", lw=1.5, zorder=4)
        ax.scatter(ex["ts"], ex["exit"], marker="X" if ex["reason"] == "손절" else "o", s=90,
                   color=color, edgecolor="white", lw=1.5, zorder=4)
        ax.annotate(NUM[i], (en["ts"], en["entry"]), xytext=(-14, 0), textcoords="offset points", ha="center", va="center",
                    fontsize=11, color=color, weight="bold", zorder=5,
                    bbox=dict(fc="white", ec="none", pad=0.5, alpha=0.85))
    for t, side, _ in skipped:
        ax.scatter(t, b.loc[t].close, marker=SIDE[side][2], s=70, facecolor="white", edgecolor=SIDE[side][1], lw=1.4, zorder=4)

    total = trades[-1][1]["pnl_today"] if trades else 0
    ax.set_title(f"{d:%m/%d}   {len(trades)}회, 당일 {total:+,}원", loc="left", fontsize=11, color="#0b0b0b")
    ax.set_xlim(d + pd.Timedelta(hours=8, minutes=55), d + pd.Timedelta(hours=15, minutes=40))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(axis="y", color="#e6e5e1", lw=0.8)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#d4d3cf")
    tx.axis("off")
    tx.text(0, 1, "\n".join(lines), va="top", ha="left", fontsize=8.8, color="#0b0b0b", linespacing=1.6,
            transform=tx.transAxes)
    return len(lines)


def main(days):
    b5 = bars5(days)
    n_lines = [len(explain(b5, day_bars(b5, d), *load_journal(d))[0]) for d in days]
    ratios = [r for n in n_lines for r in (3.4, 0.24 * n + 0.2)]
    fig, axes = plt.subplots(2 * len(days), 1, figsize=(12, sum(ratios)), gridspec_kw={"height_ratios": ratios})
    for i, day in enumerate(days):
        plot_day(axes[2 * i], axes[2 * i + 1], day, b5)
    handles = [plt.Line2D([], [], color=c, marker=m, lw=2, label=f"{n} 진입") for n, c, m in SIDE.values()]
    handles += [plt.Line2D([], [], color=MUTED, marker="^", mfc="white", lw=0, label="신호 미진입"),
                plt.Line2D([], [], color=MUTED, marker="o", lw=0, label="중심선 청산"),
                plt.Line2D([], [], color=MUTED, marker="X", lw=0, label="손절 청산"),
                plt.Line2D([], [], color=SIDE[1][1], ls=(0, (3, 2)), label="손절선 (77틱, 보유 중에만)"),
                plt.Line2D([], [], color=INK, marker="o", ms=3, lw=1.2, label="5분봉 종가"),
                plt.Line2D([], [], color="#b9b8b3", lw=0.8, label="1분 현재가"),
                plt.Rectangle((0, 0), 1, 1, fc=BAND, alpha=0.5, label="볼린저 밴드 (20, 2σ)"),
                plt.Line2D([], [], color=MUTED, ls=(0, (4, 3)), label="중심선")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.975), ncol=5, frameon=False, fontsize=8.5)
    fig.suptitle("코스닥150 F 볼린저 B 모의매매: 진입과 청산 근거", x=0.01, ha="left", y=0.995, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    out = RESULTS / f"trades_{days[0]}_{days[-1]}.png"
    fig.savefig(out, dpi=150, facecolor="white")
    print(out)


def main_simple(day):
    """하루 한 장: 메모/sim_cross_band.py 차트와 같은 모양으로 실전 거래만 표시 → results/trades_YYYYMMDD.png"""
    b5 = bars5([day])
    b = day_bars(b5, day)
    b = b[~b.auction]
    ticks, trades, start = load_journal(day)
    assert {en["ts"].replace(second=0) for en, _ in trades} <= set(b.index[b.entry != 0]), "저널 진입이 신호와 다르다"
    _, skipped = explain(b5, b, ticks, trades, start)
    skipped += [(t, int(r.raw), f"당일 봉 {WARMUP}개 전 (10/29부터 진입 안 함)")
                for t, r in b[(b.raw != 0) & (b.entry == 0)].iterrows()]
    skipped.sort(key=lambda s: s[0])
    d = pd.Timestamp(day)

    fig, (ax, tx) = plt.subplots(2, 1, figsize=(13, 6.2 + 0.24 * (len(trades) + len(skipped))),
                                 gridspec_kw={"height_ratios": [6, 0.24 * (len(trades) + len(skipped)) + 0.4]})
    ax.fill_between(b.index, b.lo, b.up, color=BAND, alpha=0.25, lw=0)
    ax.plot(b.index, b.mid, color=MUTED, lw=1.2, ls=(0, (4, 3)))
    ax.plot(b.index, b.close, color=INK, lw=1.2, marker="o", ms=2.5)
    lines, gross = [], 0
    for i, (en, ex) in enumerate(trades):
        name, color, mk = SIDE[en["side"]]
        moved = round((ex["exit"] - en["entry"]) * en["side"] / TICK)
        gross += moved * TICK * MULT
        ax.axvspan(en["ts"], ex["ts"], color=color, alpha=0.07, lw=0)
        ax.hlines(en["entry"] - en["side"] * P["stop_ticks"] * TICK, en["ts"], ex["ts"], color=color, lw=1, ls=(0, (3, 2)))
        ax.plot([en["ts"], ex["ts"]], [en["entry"], ex["exit"]], color=color, lw=2, zorder=4)
        ax.scatter(en["ts"], en["entry"], marker=mk, s=110, color=color, edgecolor="white", lw=1.5, zorder=5)
        ax.scatter(ex["ts"], ex["exit"], marker="X" if ex["reason"] == "손절" else "o", s=80,
                   color=color, edgecolor="white", lw=1.5, zorder=5)
        ax.annotate(NUM[i], (en["ts"], en["entry"]), xytext=(0, -16 * en["side"]), textcoords="offset points",
                    ha="center", va="center", fontsize=10, color=color, weight="bold", zorder=6,
                    bbox=dict(fc="white", ec="none", pad=0.5, alpha=0.85))
        why = "하단 밴드 아래 → 안 복귀" if en["side"] > 0 else "상단 밴드 위 → 안 복귀"
        lines.append(f"{NUM[i]} {en['ts']:%H:%M} {why} → {name} {en['entry']:.1f}   "
                     f"{ex['ts']:%H:%M} {'운영 종료' if ex['reason'] == '15:25' else ex['reason']} → 청산 {ex['exit']:.1f}   "
                     f"{moved:+d}틱, 수수료 포함 {ex['pnl']:+,}원")
    for t, side, why in skipped:
        ax.scatter(t, b.loc[t].close, marker=SIDE[side][2], s=60, facecolor="white", edgecolor=SIDE[side][1], lw=1.2, zorder=4)
        lines.append(f"△ {t:%H:%M} {SIDE[side][0]} 신호 미진입: {why}")

    ax.set_xlim(d + pd.Timedelta(hours=8, minutes=55), d + pd.Timedelta(hours=15, minutes=40))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(axis="y", color="#e6e5e1", lw=0.8)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    win = sum(ex["pnl"] > 0 for _, ex in trades)
    total = trades[-1][1]["pnl_today"] if trades else 0
    ax.set_title(f"{d:%m/%d}   {len(trades)}회, {win}승 {len(trades) - win}패, 수수료 포함 {total:+,}원 "
                 f"(가격손익 {gross:+,.0f}원)", loc="left", fontsize=11)
    handles = [plt.Line2D([], [], color=c, marker=m, lw=2, label=f"{n} 진입") for n, c, m in SIDE.values()]
    handles += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, label="중심선/15:25 청산"),
                plt.Line2D([], [], color=MUTED, marker="X", lw=0, label="손절 청산"),
                plt.Line2D([], [], color=MUTED, marker="^", mfc="white", lw=0, label="신호 미진입"),
                plt.Line2D([], [], color=MUTED, ls=(0, (3, 2)), label=f"손절선 ({P['stop_ticks']}틱, 보유 중에만)"),
                plt.Line2D([], [], color=MUTED, ls=(0, (4, 3)), label="중심선 (5분봉 20개 평균)"),
                plt.Line2D([], [], color=INK, marker="o", ms=3, lw=1.2, label="5분봉 종가"),
                plt.Rectangle((0, 0), 1, 1, fc=BAND, alpha=0.5, label="볼린저 밴드 5분 (20, 2σ)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.965), ncol=5, frameon=False, fontsize=8.5)
    fig.suptitle("코스닥150 F 볼린저 B 모의매매: 밴드 밖에서 안으로 복귀하면 진입, 중심선 도달 또는 77틱 손절 시 청산",
                 x=0.01, ha="left", y=0.995, fontsize=12)
    tx.axis("off")
    tx.text(0, 1, "\n".join(lines), va="top", ha="left", fontsize=8.8, linespacing=1.6, transform=tx.transAxes)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = RESULTS / f"trades_{day}.png"
    fig.savefig(out, dpi=150, facecolor="white")
    print(out)


if __name__ == "__main__":
    # --simple: 하루 한 장 (python plot_journal.py 20261028 --simple)
    args = [a for a in sys.argv[1:] if a != "--simple"]
    if "--simple" in sys.argv:
        for day in args:
            main_simple(day)
    else:
        main(args)
