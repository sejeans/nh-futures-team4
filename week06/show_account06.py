# 모의계좌 당일 체결내역, 잔고, 예수금 조회 (screenshots/ 캡처용, 주문 없음). 5주차 show_account.py 를 그대로 쓰고
# 원본 응답 저장 위치만 week06/results 로 바꾼다
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent / "week05"))
import show_account as sa  # noqa: E402

sa.RESULTS = HERE / "results"
sa._nh.LOG_DIR = HERE / "results" / "api_log"

if __name__ == "__main__":
    sa.main()
