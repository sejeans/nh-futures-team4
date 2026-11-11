# 11/13 수익률 대회 규칙(ZN 24계약, 15:00 진입 → 손절 또는 17:55 청산)을 지난 1분봉에 적용한 시뮬레이션
# 데이터: ../week03/results/bars_ZNZ26_1m_20260824_20261030.json (ZNZ26 1분봉 49일, 시각은 한국 시간)
#         ../week03/results/bars_ZN_cont_1d_20261111_1531.json (연결 일봉, TSMOM 신호용)
# 신호: compete.py 와 같은 함수(adjust, roll_days, tsmom). D일 신호 = D-1 종가 기준
# 체결: 15:00 봉 시가에 진입, 매 분 종가로 손절 확인, 17:55 봉 종가에 청산. 진입과 청산마다 0.5틱 불리 + 수수료 편도 $8/계약
# 주문 없음. 저장된 파일만 읽는다.
import collections
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

W3 = Path(__file__).resolve().parent.parent / "week03"
sys.path.insert(0, str(W3))
from strategies import adjust, daily, roll_days, tsmom  # noqa: E402

N, TICK, TICK_USD, FEE, SLIP = 24, 1 / 64, 15.625, 8.0, 0.5
MIN_FILE = W3 / "results" / "bars_ZNZ26_1m_20260824_20261030.json"
DAY_FILE = W3 / "results" / "bars_ZN_cont_1d_20261111_1531.json"


def run(bars, side, stop_ticks, start="1500", end="1755"):
    """bars: {HHMM: 1분봉}. 반환 (USD 손익, 청산 사유) 또는 None(15:00 봉 없음)"""
    if start not in bars:
        return None
    entry = float(bars[start]["occurs1_open_pric"]) + side * SLIP * TICK
    ks = [k for k in sorted(bars) if start <= k <= end]
    for k in ks[1:]:
        c = float(bars[k]["occurs1_close_pric"])
        if (c - entry) * side / TICK <= -stop_ticks:
            exit_, why = c - side * SLIP * TICK, "손절"
            break
    else:
        exit_, why = float(bars[ks[-1]]["occurs1_close_pric"]) - side * SLIP * TICK, "시간"
    return ((exit_ - entry) * side / TICK * TICK_USD - 2 * FEE) * N, why


def selfcheck():
    b = lambda o, c: {"occurs1_open_pric": str(o), "occurs1_close_pric": str(c)}  # noqa: E731
    up = {"1500": b(100, 100), "1501": b(100, 100 + 20 * TICK), "1755": b(100, 100 + 20 * TICK)}
    assert run(up, -1, 10)[1] == "손절" and run(up, 1, 10)[1] == "시간"
    assert run(up, 1, 10)[0] == ((20 - 1) * TICK_USD - 2 * FEE) * N  # 20틱 이익 - 슬리피지 1틱 - 수수료
    assert run({"1501": b(1, 1)}, 1, 10) is None


def main():
    selfcheck()
    d = daily("ZN", DAY_FILE, until="2026-11-11")
    sig = tsmom(adjust(d, roll_days(d, TICK)).close).shift(1)
    by = collections.defaultdict(dict)
    for x in json.loads(MIN_FILE.read_text(encoding="utf-8"))["data"]:
        by[x["occurs1_ref_dt"]][x["occurs1_exch_tm"][:4]] = x
    side_of = {day: int(sig.get(pd.Timestamp(day), 0) or 0) for day in by}
    print("신호 분포:", dict(collections.Counter(side_of.values())), f"/ {len(by)}일")
    print(f"{N}계약 왕복 비용 약 ${N * (2 * SLIP * TICK_USD + 2 * FEE):.0f}")
    out = {}
    mv = []  # 15:00 시가 → 17:55 종가 변화와 고가-저가 범위 (틱)
    for x in by.values():
        ks = [k for k in sorted(x) if "1500" <= k <= "1755"]
        if "1500" in x and ks:
            o, c = float(x["1500"]["occurs1_open_pric"]), float(x[ks[-1]]["occurs1_close_pric"])
            hi = max(float(x[k]["occurs1_high_pric"]) for k in ks)
            lo = min(float(x[k]["occurs1_low_pric"]) for k in ks)
            mv.append((abs(c - o) / TICK, (hi - lo) / TICK))
    mv = np.array(mv)
    out["move_ticks"] = {k: {"median": float(np.median(a)), "p90": float(np.percentile(a, 90)), "max": float(a.max())}
                         for k, a in (("open_to_close", mv[:, 0]), ("high_low", mv[:, 1]))}
    print(f"15:00→17:55 ({len(mv)}일)", out["move_ticks"])
    for name, fn in [("TSMOM", lambda day: side_of[day]), ("항상 매수", lambda day: 1), ("항상 매도", lambda day: -1)]:
        for stop in ((8, 10, 15, 10**6) if name == "TSMOM" else (10,)):
            r = [(day,) + o for day in sorted(by) if fn(day) and (o := run(by[day], fn(day), stop))]
            p = np.array([v[1] for v in r])
            eq = np.cumsum(p)
            row = {"days": len(p), "mean": round(p.mean()), "median": round(float(np.median(p))),
                   "win": round(float(np.mean(p > 0)), 2), "stops": sum(v[2] == "손절" for v in r),
                   "worst": round(p.min()), "best": round(p.max()), "sum": round(p.sum()),
                   "max_dd": round((eq - np.maximum.accumulate(eq)).min())}
            out[f"{name} 손절 {stop if stop < 10**6 else '없음'}"] = row
            print(f"{name:6s} 손절 {stop if stop < 10**6 else '없음':>3}", row)
    f = Path(__file__).resolve().parent / "results" / "sim_compete.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장:", f.name)


if __name__ == "__main__":
    main()
