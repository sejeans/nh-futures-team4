# 6주차 위험관리 규칙. backtest06.py 와 trade06.py 가 같은 함수를 쓴다 (2주차 strategy.py 와 같은 방식)
# 전략(진입, 중심선 청산)은 2주차 볼린저 평균회귀 그대로: week02/strategy.py bollinger(), 당일 봉 20개 대기 규칙
from dataclasses import dataclass

TICK, MULT = 0.1, 10_000          # 코스닥150 선물 호가 단위, 승수
FEE_PER_LOT = 2_400               # 1계약 왕복 수수료 (2주차 10/26 실측 0.0098%, 약 1,220포인트 기준)
STOP_TICKS = 77                   # 2주차 그대로: 5분봉 ATR(14) 중앙값 38.36틱 × 2 (week02/params_bollinger.ipynb)
LOSS_LIMIT_PER_LOT = 154_000      # 2주차 그대로: 손절 2회분 (77틱 × 2 × 1,000원), 계약 수에 비례
EXIT_AT = "15:25"                 # 장 마감 전 전량 청산 (2주차 그대로)


@dataclass(frozen=True)
class Rules:
    stop: bool = True             # 77틱 손절
    stop_touch: bool = False      # False: 1분 종가로 손절 판정 (2주차) / True: 가격이 손절가에 닿는 즉시 (6주차, 실전 10초 확인)
    limit: str | None = "realized"  # None / "realized": 실현 손실이 한도에 닿으면 진입 중지 (2주차) / "worst": 다음 거래가 손절돼도 한도 안일 때만 진입 (6주차)
    lots: int = 1                 # 진입 계약 수
    split: bool = False           # True: 중심선에서 절반 청산, 나머지는 손절가를 진입가로 올리고 반대편 밴드 또는 15:25 에 청산


def stop_price(side, entry, stage):
    """stage 0: 진입가에서 77틱 불리 / stage 1(분할 청산 뒤): 진입가 (본전)"""
    return round(entry - side * STOP_TICKS * TICK, 1) if stage == 0 else entry


def stop_hit(side, entry, stage, px):
    return side * (px - stop_price(side, entry, stage)) <= 1e-9


def worst_loss(lots):
    """다음 거래가 손절될 때의 손실 추정: 손절 폭 + 진입, 청산 슬리피지 각 1틱 + 수수료"""
    return lots * ((STOP_TICKS + 2) * TICK * MULT + FEE_PER_LOT)


def entry_allowed(rules, pnl_today):
    if rules.limit is None:
        return True
    limit = LOSS_LIMIT_PER_LOT * rules.lots
    if rules.limit == "realized":
        return pnl_today > -limit
    return pnl_today - worst_loss(rules.lots) >= -limit


def selfcheck():
    s = STOP_TICKS * TICK
    assert stop_hit(1, 1000, 0, 1000 - s) and not stop_hit(1, 1000, 0, 1000 - s + TICK)
    assert stop_hit(-1, 1000, 0, 1000 + s) and not stop_hit(-1, 1000, 0, 1000 + s - TICK)
    assert stop_hit(1, 1000, 1, 1000) and not stop_hit(1, 1000, 1, 1000.1)
    r2, r6 = Rules(limit="realized"), Rules(limit="worst")
    assert entry_allowed(r2, -100_000) and not entry_allowed(r2, -154_000)   # 2주차: 손절 1회 뒤에도 진입
    assert entry_allowed(r6, 0) and not entry_allowed(r6, -81_400)           # 6주차: 손절 1회 뒤엔 다음 손절이 한도를 넘음
    assert worst_loss(1) == 81_400


selfcheck()
