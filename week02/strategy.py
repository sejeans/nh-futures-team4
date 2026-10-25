# 후보별 신호 함수 — backtest.py 와 trade.py 가 같이 쓴다
# 반환: 봉 마감 시각(close_t) 기준 DataFrame
#   entry      +1 매수 / -1 매도 / 0 없음
#   exit_long  매수 보유 중 전략 청산 신호
#   exit_short 매도 보유 중 전략 청산 신호
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "results" / "params_bollinger.json").read_text(encoding="utf-8"))
assert P["bollinger"]["carry_over"], "전일 이어쓰기만 구현했다"

TICK, MULT = 0.1, 10_000  # 호가단위·승수 (계획 3절)

# 후보 A·C 는 계획 4-2 의 관례값. 계산하지 않고 고정
EMA_FAST, EMA_SLOW = 5, 20
OR_FROM, OR_UNTIL = "09:00", "09:30"


def _frame(b, entry, exit_long, exit_short):
    return pd.DataFrame({"entry": entry.astype(int), "exit_long": exit_long,
                         "exit_short": exit_short}).set_index(b.close_t)


def bollinger(b5, oi=None):
    """후보 B. 5분봉. 직전 종가 밴드 밖 → 이번 종가 밴드 안 복귀 시 진입, 중심선 도달 시 청산.
    oi="up"/"down": 신호 봉의 미결제약정이 늘었을/줄었을 때만 진입"""
    n, k = P["bollinger"]["n"], P["bollinger"]["k"]
    c, pc = b5.close, b5.close.shift()
    mid = c.rolling(n).mean()
    sd = c.rolling(n).std(ddof=P["bollinger"]["std_ddof"])
    up, lo = mid + k * sd, mid - k * sd
    ok = b5.day.eq(b5.day.shift()) & ~b5.auction  # 하루 첫 봉은 직전 봉이 전일이라 제외
    if oi:
        ok &= np.sign(b5.oi.diff()) == (1 if oi == "up" else -1)
    long_ = ok & (pc < lo.shift()) & (c >= lo)
    short = ok & (pc > up.shift()) & (c <= up)
    return _frame(b5, long_.astype(int) - short.astype(int), c >= mid, c <= mid)


def ema_cross(b1):
    """후보 A. 1분봉 EMA(5)·EMA(20) 교차 진입, 반대 교차 청산"""
    f = b1.close.ewm(span=EMA_FAST, adjust=False).mean()
    s = b1.close.ewm(span=EMA_SLOW, adjust=False).mean()
    golden = (f > s) & (f.shift() <= s.shift())
    dead = (f < s) & (f.shift() >= s.shift())
    return _frame(b1, golden.astype(int) - dead.astype(int), dead, golden)


def opening_range(b1):
    """후보 C. 09:00~09:30 1분봉 고가·저가를 종가로 돌파하면 진입. 전략 청산 신호 없음 (손절·15:25 만)"""
    hm = pd.Series(b1.index.strftime("%H:%M"), index=b1.index)
    rng = (hm >= OR_FROM) & (hm < OR_UNTIL)
    hi = b1.high.where(rng).groupby(b1.day).transform("max")
    lo = b1.low.where(rng).groupby(b1.day).transform("min")
    after = hm >= OR_UNTIL
    no = pd.Series(False, index=b1.index)
    return _frame(b1, (after & (b1.close > hi)).astype(int) - (after & (b1.close < lo)).astype(int), no, no)
