# 후보 A·B·C 백테스트 — 1분봉을 따라가며 매 분 손절을 확인한다 (실전 루프와 같은 방식)
import json
from datetime import datetime

import numpy as np
import pandas as pd

from fetch_bars import BARS_1M, BARS_5M, RESULTS, load
from strategy import MULT, P, TICK, bollinger, ema_cross, opening_range

ENTRY_FROM, ENTRY_UNTIL = P["entry_window_close_time"]
EXIT_AT = P["force_exit_time"]
STOP_TICKS = P["stop_ticks"]
LOSS_LIMIT = P["daily_loss_limit_krw"]
SLIP_TICKS = 1   # 진입·청산마다 1틱 불리 (계획 4-3)
FEE_KRW = 0      # 수수료: 10/26 deposit 실측 후 채운다 (계획 4-3)
PERIODS = {"선택": ("2026-09-11", "2026-10-08"), "검증": ("2026-10-12", "2026-10-23")}


def run(b1, sig, max_per_day=None):
    """b1: 1분봉, sig: 봉 마감 시각 기준 신호. 신호 봉의 1분 종가로 체결한다고 본다."""
    entry = sig.entry[sig.entry != 0].to_dict()
    exits = {1: set(sig.index[sig.exit_long]), -1: set(sig.index[sig.exit_short])}
    trades = []
    for day, g in b1[~b1.auction].groupby("day"):
        pos, n, pnl_day = 0, 0, 0.0

        def close_out(t, px, reason):
            krw = round((px - pos * SLIP_TICKS * TICK - e_px) * pos * MULT - FEE_KRW)
            trades.append({"day": day, "side": pos, "entry_t": e_t, "entry_px": e_px,
                           "exit_t": t, "exit_px": round(px - pos * SLIP_TICKS * TICK, 1), "reason": reason, "krw": krw})
            return krw

        for t, px in zip(g.close_t, g.close):
            hm = t.strftime("%H:%M")
            if pos:
                reason = ("15:25" if hm >= EXIT_AT else
                          "손절" if round((px - e_px) * pos / TICK) <= -STOP_TICKS else
                          "신호" if t in exits[pos] else None)
                if reason:
                    pnl_day += close_out(t, px, reason)
                    pos = 0
                continue  # 보유 중이거나 방금 청산한 봉에서는 진입하지 않는다
            side = entry.get(t, 0)
            if (side and ENTRY_FROM <= hm < ENTRY_UNTIL and pnl_day > -LOSS_LIMIT
                    and (max_per_day is None or n < max_per_day)):
                pos, n = side, n + 1
                e_t, e_px = t, round(px + side * SLIP_TICKS * TICK, 1)
        if pos:  # 데이터가 15:25 전에 끝난 날
            close_out(t, px, "데이터끝")
    return pd.DataFrame(trades)


def summary(tr, days):
    if tr.empty:
        return {"거래": 0, "하루거래": 0.0}
    eq = np.concatenate([[0], tr.krw.cumsum()])
    win, loss = tr.krw[tr.krw > 0], tr.krw[tr.krw <= 0]
    return {
        "거래": len(tr),
        "하루거래": round(len(tr) / days, 2),
        "승률": round(len(win) / len(tr), 3),
        "순손익": int(tr.krw.sum()),
        "평균이익": int(win.mean()) if len(win) else 0,
        "평균손실": int(loss.mean()) if len(loss) else 0,
        "손익비": round(win.sum() / -loss.sum(), 2) if loss.sum() < 0 else None,
        "최대낙폭": int((eq - np.maximum.accumulate(eq)).min()),
        "청산": tr.reason.value_counts().to_dict(),
    }


def selfcheck():
    # 100 매수(체결 100.1) → 손절 1틱 전 → 손절 1틱 넘김(청산) → 그 뒤 봉은 무시
    s = STOP_TICKS * TICK
    t = pd.date_range("2026-01-05 09:00", periods=5, freq="min")
    b1 = pd.DataFrame({"close": [100, 100, 100 - s + 0.2, 100 - s, 90.0], "day": t.normalize(),
                       "auction": False, "close_t": t}, index=t)
    sig = pd.DataFrame({"entry": [1, 0, 0, 0, 1], "exit_long": False, "exit_short": False}, index=t)
    tr = run(b1, sig, max_per_day=1)
    assert len(tr) == 1 and tr.reason[0] == "손절" and tr.exit_t[0] == t[3], tr
    assert round(tr.krw[0]) == -(STOP_TICKS + 2) * TICK * MULT, tr  # 손절폭 + 진입·청산 슬리피지 2틱


def main():
    selfcheck()
    b1 = load(BARS_1M, 1)
    b5 = pd.concat([load(p, 5) for p in BARS_5M]).sort_index()
    assert not b5.index.duplicated().any()

    # 5분봉 종가 = 그 안 마지막 1분봉 종가인지 (B 신호를 1분 종가로 체결하는 근거)
    c1 = b1[~b1.auction].set_index("close_t").close
    m = b5[~b5.auction].set_index("close_t").close
    same = c1.reindex(m.index)
    diff = (same - m).abs()
    print(f"5분봉 종가 vs 1분봉 종가: {len(m)}봉 중 불일치 {(diff > 1e-9).sum()}, 1분봉 없음 {same.isna().sum()}")

    cands = {
        "A EMA(5,20) 1분": (ema_cross(b1), None),
        "B 볼린저 5분": (bollinger(b5), None),
        "B + OI증가": (bollinger(b5, "up"), None),
        "B + OI감소": (bollinger(b5, "down"), None),
        "C 시가범위 돌파": (opening_range(b1), 1),
    }
    ndays = {k: b1.day[(b1.day >= s) & (b1.day <= e)].nunique() for k, (s, e) in PERIODS.items()}

    rows, all_tr = [], []
    for name, (sig, cap) in cands.items():
        tr = run(b1, sig, cap)
        tr.insert(0, "cand", name)
        all_tr.append(tr)
        for per, (s, e) in PERIODS.items():
            sub = tr[(tr.day >= s) & (tr.day <= e)] if not tr.empty else tr
            rows.append({"후보": name, "구간": per, **summary(sub, ndays[per])})

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(f"\n손절 {STOP_TICKS}틱 · 일일 한도 {LOSS_LIMIT:,.0f}원 · 슬리피지 {SLIP_TICKS}틱/회 · 수수료 {FEE_KRW}원 "
          f"· 선택 {ndays['선택']}일 / 검증 {ndays['검증']}일")
    print(res.drop(columns="청산").to_string(index=False))
    print("\n청산 사유")
    print(res[["후보", "구간", "청산"]].to_string(index=False))

    pd.concat(all_tr).to_csv(RESULTS / "backtest_trades.csv", index=False, encoding="utf-8-sig")
    (RESULTS / "backtest_summary.json").write_text(json.dumps({
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "params": "week02/results/params_bollinger.json",
        "assumptions": {"slip_ticks_per_side": SLIP_TICKS, "fee_krw": FEE_KRW,
                        "fill": "signal bar 1-min close", "stop_check": "every 1-min close"},
        "days": ndays,
        "rows": rows,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n저장: results/backtest_trades.csv, results/backtest_summary.json")


if __name__ == "__main__":
    main()
