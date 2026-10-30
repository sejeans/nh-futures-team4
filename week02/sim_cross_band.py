# 단순 교차 시뮬레이션: 골든크로스 매수 / 데드크로스 매도, 청산 규칙만 바꿔 가며 비교
# 일일 한도·15:25 청산 없음. 보유 중 교차는 무시. 1분 종가로 판정·체결, 슬리피지 없음
# 사용: python week02/sim_cross_band.py 20261026 20261027 [--mid]
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from fetch_bars import BARS_1M, RESULTS, SYM, load  # noqa: E402
from plot_journal import INK, MUTED, BAND, NUM, SIDE, bars5  # noqa: E402
from strategy import EMA_FAST, EMA_SLOW, MULT, P, TICK  # noqa: E402

FEE = 2393 / ((1221.0 + 1220.3) * MULT)  # 10/26 실측 (trade.py 와 같은 값)
STOP = P["stop_ticks"]  # 77
# 이름: (반대편 밴드 도달 청산, 손절 틱, 익절 틱)
VARIANTS = {
    "band": ("교차 진입, 반대편 밴드 도달 시 청산 (손절 없음)", True, None, None),
    "band_stop": (f"교차 진입, 반대편 밴드 도달 또는 {STOP}틱 손절 시 청산", True, STOP, None),
    "bracket": (f"교차 진입, +{STOP}틱 익절 또는 -{STOP}틱 손절 시 청산 (밴드 없음)", False, STOP, STOP),
}


def simulate(b, band, stop, take):
    trades, pos = [], 0
    for t, r in b.iterrows():
        if pos:
            ticks = round((r.close - e["entry_px"]) * pos / TICK)
            reason = (f"손절 {stop}틱" if stop and ticks <= -stop else
                      f"익절 {take}틱" if take and ticks >= take else
                      "밴드 도달" if band and ((pos > 0 and r.close >= r.up) or (pos < 0 and r.close <= r.lo)) else None)
            if reason:
                trades.append({**e, "exit_t": t, "exit_px": r.close, "reason": reason})
                pos = 0
        elif r.cross:
            pos = int(r.cross)
            e = {"side": pos, "entry_t": t, "entry_px": r.close}
    if pos:
        trades.append({**e, "exit_t": t, "exit_px": r.close, "reason": "미청산"})
    tr = pd.DataFrame(trades)
    tr["ticks"] = ((tr.exit_px - tr.entry_px) * tr.side / TICK).round().astype(int)
    tr["gross"] = tr.ticks * TICK * MULT
    tr["net"] = (tr.gross - (tr.entry_px + tr.exit_px) * FEE * MULT).round().astype(int)
    return tr


def plot(b, tr, title, band, out):
    x = pd.Series(range(len(b)), index=b.index)  # 봉 순서: 장 마감~다음 날 시작 사이 빈 시간 없이 이어 붙임
    fig, (ax, tx) = plt.subplots(2, 1, figsize=(13, 6.2 + 0.24 * len(tr)),
                                 gridspec_kw={"height_ratios": [6, 0.24 * len(tr) + 0.4]})
    ax.fill_between(x, b.lo, b.up, color=BAND, alpha=0.25 if band else 0.12, lw=0)
    if "ema_f" in b:
        ax.plot(x, b.close, color=INK, lw=1)
        ax.plot(x, b.ema_f, color="#1baf7a", lw=1)
        ax.plot(x, b.ema_s, color="#6250d6", lw=1)
    else:
        ax.plot(x, b.mid, color=MUTED, lw=1.2, ls=(0, (4, 3)))
        ax.plot(x, b.close, color=INK, lw=1.2, marker="o", ms=2.5)
    held = pd.Series(False, index=b.index)
    for r in tr.itertuples():
        held[r.entry_t:r.exit_t] = True
    for t, c in b.cross[(b.cross != 0) & held].items():
        ax.scatter(x[t], b.close[t], marker=SIDE[c][2], s=22, facecolor="white", edgecolor=SIDE[c][1], lw=1, zorder=3)
    lines = []
    for i, r in enumerate(tr.itertuples()):
        name, color, mk = SIDE[r.side]
        x0, x1 = x[r.entry_t], x[r.exit_t]
        ax.axvspan(x0, x1, color=color, alpha=0.07, lw=0)
        ax.plot([x0, x1], [r.entry_px, r.exit_px], color=color, lw=2, zorder=4)
        ax.scatter(x0, r.entry_px, marker=mk, s=110, color=color, edgecolor="white", lw=1.5, zorder=5)
        ax.scatter(x1, r.exit_px, marker="X" if r.reason.startswith("손절") else "o", s=80,
                   color=color, edgecolor="white", lw=1.5, zorder=5)
        ax.annotate(NUM[i] if i < len(NUM) else str(i + 1), (x0, r.entry_px), xytext=(0, -16 * r.side),
                    textcoords="offset points", ha="center", va="center", fontsize=10, color=color, weight="bold",
                    zorder=6, bbox=dict(fc="white", ec="none", pad=0.5, alpha=0.85))
        cross = "골든크로스" if r.side > 0 else "데드크로스"
        end = "장 마감까지 청산 조건 미도달, 마지막 가격" if r.reason == "미청산" else f"{r.exit_t:%m/%d %H:%M} {r.reason} → 청산"
        lines.append(f"{NUM[i] if i < len(NUM) else i + 1} {r.entry_t:%m/%d %H:%M} {cross} → {name} {r.entry_px:.1f}   "
                     f"{end} {r.exit_px:.1f}   {r.ticks:+d}틱, 수수료 포함 {r.net:+,}원")
    day_start = b.groupby("day").head(1).index
    for t in day_start[1:]:
        ax.axvline(x[t], color=MUTED, lw=0.8, ls=":")
    hours = b.index[b.index.strftime("%M") == "00"]
    ax.set_xticks([x[t] for t in hours],
                  [t.strftime("%m/%d\n%H:%M") if t.hour == 9 else t.strftime("%H:%M") for t in hours], fontsize=8)
    ax.set_xlim(-5, len(b) + 5)
    ax.grid(axis="y", color="#e6e5e1", lw=0.8)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    win = (tr.net > 0).sum()
    ax.set_title(f"{len(tr)}회, {win}승 {len(tr) - win}패, 수수료 포함 {tr.net.sum():+,}원 (가격손익 {tr.gross.sum():+,.0f}원)",
                 loc="left", fontsize=11)
    handles = [plt.Line2D([], [], color=c, marker=m, lw=2, label=f"{n} 진입") for n, c, m in SIDE.values()]
    handles += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, label="밴드/익절 청산"),
                plt.Line2D([], [], color=MUTED, marker="X", lw=0, label="손절 청산"),
                plt.Line2D([], [], color=MUTED, marker="^", mfc="white", lw=0, label="교차 (보유 중이라 무시)"),
                *([plt.Line2D([], [], color="#1baf7a", lw=1, label=f"EMA({EMA_FAST}) 1분"),
                   plt.Line2D([], [], color="#6250d6", lw=1, label=f"EMA({EMA_SLOW}) 1분"),
                   plt.Line2D([], [], color=INK, lw=1, label="1분 종가")] if "ema_f" in b else
                  [plt.Line2D([], [], color=MUTED, ls=(0, (4, 3)), label="중심선 (5분봉 20개 평균)"),
                   plt.Line2D([], [], color=INK, marker="o", ms=3, lw=1.2, label="5분봉 종가")]),
                plt.Rectangle((0, 0), 1, 1, fc=BAND, alpha=0.5,
                              label="볼린저 밴드 5분 (20, 2σ)" + ("" if band else ", 이 규칙에선 미사용"))]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.965), ncol=4, frameon=False, fontsize=8.5)
    fig.suptitle(f"단순 교차 전략: {title}", x=0.01, ha="left", y=0.995, fontsize=12)
    tx.axis("off")
    tx.text(0, 1, "\n".join(lines), va="top", ha="left", fontsize=8.8, linespacing=1.6, transform=tx.transAxes)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out, dpi=150, facecolor="white")
    plt.close(fig)


def main_mid(days):
    """5분봉 종가가 중심선을 위로 뚫으면 매수 → 상단 밴드 / 아래로 뚫으면 매도 → 하단 밴드. 그 외 규칙 없음"""
    b = bars5(days)
    b = b[~b.auction]
    above = b.close > b.mid
    b["cross"] = (above & ~above.shift(fill_value=False)).astype(int) - (~above & above.shift(fill_value=True)).astype(int)
    b = b[b.day.isin(pd.to_datetime(days))]
    tr = simulate(b, True, None, None)
    title = "5분봉 종가가 중심선을 위로 돌파하면 매수/아래로 돌파하면 매도, 반대편 밴드 도달 시 청산 (그 외 규칙 없음)"
    win = (tr.net > 0).sum()
    print(f"{len(tr)}회, {win}승 {len(tr) - win}패, 가격손익 {tr.gross.sum():+,.0f}원, 수수료 포함 {tr.net.sum():+,}원, "
          f"청산 {tr.reason.value_counts().to_dict()}")
    print(tr.assign(entry_t=tr.entry_t.dt.strftime("%m/%d %H:%M"), exit_t=tr.exit_t.dt.strftime("%m/%d %H:%M"))
          [["entry_t", "side", "entry_px", "exit_t", "exit_px", "reason", "ticks", "net"]].to_string(index=False))
    out = RESULTS / f"sim_mid_cross_{days[0]}_{days[-1]}.png"
    plot(b, tr, title, True, out)
    print(out)


def main(days):
    b1 = pd.concat([load(BARS_1M, 1)] + [load(f, 1) for f in RESULTS.glob(f"bars_{SYM}_1m_2026102*.json")])
    b1 = b1[~b1.index.duplicated()].sort_index()
    b1 = b1[~b1.auction].set_index("close_t")
    f = b1.close.ewm(span=EMA_FAST, adjust=False).mean()   # 10/23 이전부터 이어서 계산 (예열)
    s = b1.close.ewm(span=EMA_SLOW, adjust=False).mean()
    b1["ema_f"], b1["ema_s"] = f, s
    b1["cross"] = ((f > s) & (f.shift() <= s.shift())).astype(int) - ((f < s) & (f.shift() >= s.shift())).astype(int)
    b5 = bars5(days)[["up", "lo", "mid"]]
    b = pd.merge_asof(b1, b5, left_index=True, right_index=True)  # 그 분까지 확정된 5분봉 밴드
    b = b[b.day.isin(pd.to_datetime(days))]

    for key, (title, band, stop, take) in VARIANTS.items():
        tr = simulate(b, band, stop, take)
        win = (tr.net > 0).sum()
        print(f"\n== {title}\n{len(tr)}회, {win}승 {len(tr) - win}패, 가격손익 {tr.gross.sum():+,.0f}원, "
              f"수수료 포함 {tr.net.sum():+,}원, 청산 {tr.reason.value_counts().to_dict()}")
        out = RESULTS / f"sim_cross_{key}_{days[0]}_{days[-1]}.png"
        plot(b, tr, title, band, out)
        print(out)


if __name__ == "__main__":
    # --mid: 중심선 교차 버전 (plot_journal 차트의 회색 점선)
    args = [a for a in sys.argv[1:] if a != "--mid"]
    (main_mid if "--mid" in sys.argv else main)(args)
