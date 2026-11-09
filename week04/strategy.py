# 4주차 전략 규칙 — 국채선물 3년·10년 커브 스프레드 평균회귀 (DV01 중립 3:1)
# 2026-11-09 14:5x, 백테스트 손익을 보기 전에 세진이 정함 (N=10, k=1.5, 손절 4bp). 결과를 본 뒤 바꾸지 않는다.
# 사전 기준: 왕복 비용 0.78bp ≤ 진입 시 평균선 거리 중앙값의 20% → N=10·k=1.5 에서 4.52bp, 17% 로 통과 (손익 계산 전)
# 백테스트(backtest.py)와 실전(live.py)이 같은 함수를 쓴다
import pandas as pd

N = 10            # 평균·표준편차를 구하는 지난 거래일 수 (일별 반감기 5.9일의 약 2배)
K = 1.5           # 진입 |z|
STOP_BP = 4.0     # 진입 후 스프레드가 불리하게 4bp 더 가면 손절 (장중 범위 중앙 2.6bp 보다 크게)
MAX_DAYS = 10     # 진입 후 10거래일이 지나면 시간 청산
SIGNAL_TM = "15:30"  # 15:35 부터 종가 단일가 → 연속매매 안에서 끝낸다
RATIO = (3, 1)    # 3년 3계약 : 10년 1계약 (DV01 28,792 : 86,602원, explore_summary.json)
COST_KRW = 67_680  # 왕복 비용 실측 (manual_roundtrip_20261109_143920.json): 호가 넘기 40,000 + 수수료 27,680


def zscore(daily):
    """daily: 날짜별 SIGNAL_TM 스프레드(bp). 오늘 값은 평균에 넣지 않는다"""
    m = daily.rolling(N).mean().shift(1)
    sd = daily.rolling(N).std().shift(1)
    return (daily - m) / sd


def entry_side(z):
    """+1 = 스티프닝(3년 매수 3·10년 매도 1), -1 = 플래트닝, 0 = 없음"""
    if pd.isna(z):
        return 0
    return 1 if z <= -K else -1 if z >= K else 0


def exit_reason(side, z, spread, entry_spread, days_held):
    """보유 중 청산 사유. side +1 은 스프레드가 오르면(스티프닝) 이익"""
    if side * (spread - entry_spread) <= -STOP_BP:
        return "손절"
    if not pd.isna(z) and side * z >= 0:
        return "평균 복귀"
    if days_held >= MAX_DAYS:
        return "시간 청산"
    return None


def selfcheck():
    assert entry_side(-1.6) == 1 and entry_side(1.5) == -1 and entry_side(0.3) == 0 and entry_side(float("nan")) == 0
    assert exit_reason(1, -1.0, 20.0, 24.0, 1) == "손절"          # 스티프닝 진입 후 4bp 더 평평해짐
    assert exit_reason(-1, 1.0, 28.0, 24.0, 1) == "손절"
    assert exit_reason(1, 0.1, 25.0, 24.0, 1) == "평균 복귀"
    assert exit_reason(1, -1.0, 23.0, 24.0, 10) == "시간 청산"
    assert exit_reason(1, -1.0, 23.0, 24.0, 3) is None


if __name__ == "__main__":
    selfcheck()
    print("ok")
