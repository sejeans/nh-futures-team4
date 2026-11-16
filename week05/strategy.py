# 5주차 전략 규칙 — 10년 국채선물(KTB10) 전일 장중 반전. 백테스트(backtest.py)와 실전(live.py)이 같은 함수를 쓴다
#
# 근거 (analysis.py, results/analysis_summary.json, 2022~2024 학습·검증 구간만 사용)
#   오늘 장중 변동(시가→종가) = BETA × 어제 장중 변동. BETA = -0.155 (t = -4.25, 2022~2024, 상수항 없음)
#   미국 10년(ZN) 밤사이 변동은 KTB10 시가 갭의 57% 를 설명하지만, 개장 후 장중 변동은 예측하지 못했다 → 신호에 넣지 않음
#
# 2026-11-16 10:35, 시험 구간(2025-01-01~2026-11-13) 손익을 보기 전에 정함. 결과를 본 뒤 바꾸지 않는다
import math

BETA = -0.155       # analysis_summary.json final_beta
SLIP_PT = 0.01      # 호가 넘기: 시장가 왕복이 매수·매도 1호가에서 체결 → 1틱 (4주차 11/09 수동 왕복 실측)
FEE_PT = 0.0071     # 수수료 왕복: 거래대금의 0.00329% × 2 (4주차 11/09 실측) × 가격 108
COST_PT = SLIP_PT + FEE_PT  # 0.0171 = 1계약 왕복 17,100원 (1포인트 = 1,000,000원). 백테스트는 체결가를 시가·종가로 보므로 둘 다 뺀다
MIN_PREV = 0.11     # |예상 이익| = |BETA × 어제 장중| ≥ 왕복 비용 → |어제 장중| ≥ 0.0171 / 0.155 = 0.110
STOP_PT = 0.50      # 진입가 대비 손절 폭(포인트) = 1계약 50만원. backtest.py --stops 로 학습·검증 구간에서만 비교해 정함:
#                     0.2·0.3 은 손익을 깎고(검증 0.2 는 적자), 0.5 는 손절 없음과 학습 구간 손익이 거의 같다(2,672만 vs 2,677만원).
#                     장중 고저 범위 중앙값 0.51 과 같은 폭의 '사고 대비' 손절로 둔다
ENTRY_TM = "09:00"  # 모의 국내 운영 09:00 부터 (과제 공지). 시가(08:45) 대신 09:00 첫 시세로 진입
EXIT_TM = "15:30"   # 15:35 부터 종가 단일가 → 연속매매 안에서 청산 (4주차와 같음)
QTY = 1


def side(prev_intra):
    """+1 매수 / -1 매도 / 0 없음. prev_intra = 어제 시가→종가 (가격 포인트)"""
    if prev_intra is None or math.isnan(prev_intra):
        return 0
    if abs(prev_intra) < MIN_PREV - 1e-9:
        return 0
    return -1 if prev_intra > 0 else 1


def stop_price(side_, entry_px):
    if STOP_PT is None or not side_:
        return None
    return round(entry_px - side_ * STOP_PT, 2)


def stopped(side_, entry_px, px):
    sp = stop_price(side_, entry_px)
    return sp is not None and side_ * (px - sp) <= 0


def selfcheck():
    assert side(0.20) == -1 and side(-0.15) == 1
    assert side(0.10) == 0 and side(-0.109) == 0 and side(0.11) == -1 and side(float("nan")) == 0
    assert stopped(1, 108.0, 107.0) == (STOP_PT is not None and STOP_PT <= 1.0)
    assert not stopped(1, 108.0, 108.05)


if __name__ == "__main__":
    selfcheck()
    print("ok", {"BETA": BETA, "MIN_PREV": MIN_PREV, "STOP_PT": STOP_PT})
