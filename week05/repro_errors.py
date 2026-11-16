# 오류 제보 재현 (조회만, 주문 없음). 요청과 응답 원문은 results/repro_log/ 에 남는다
#   1) 해외 현재가: Iccurs1 에 종목 1개씩 → 정상 / 2개 → HTTP 200 빈 본문
#   2) 해외 예수금: biz_dt 에 오늘 날짜 → 정상 / 빈 값 → 400 ETR018 (명세는 필수 아님 N)
#   .venv/Scripts/python.exe -X utf8 week05/repro_errors.py
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "week03"))
sys.path.insert(0, str(HERE.parent / "week02"))
import nh as _nh  # noqa: E402
import nh_os  # noqa: E402

_nh.LOG_DIR = HERE / "results" / "repro_log"
_nh.RETRIES = 0  # 재현이 목적이므로 재시도하지 않는다
P = "/trade/v1/overseas/"
o = nh_os.NHOverseas()


def run(name, path, body):
    try:
        res = o.call(path, body)
        print(f"{name}: HTTP 200, 본문 {str(res)[:120]}")
    except _nh.NHError as e:
        print(f"{name}: {e}")


ZN = {"iccurs1_exch_cd": "FCME", "iccurs1_sym": "ZNZ26"}
ZF = {"iccurs1_exch_cd": "FCME", "iccurs1_sym": "ZFZ26"}
for i in range(3):
    run(f"[{i + 1}] 현재가 ZN 1종목", P + "price", {"Iccurs1": [ZN]})
    run(f"[{i + 1}] 현재가 ZF 1종목", P + "price", {"Iccurs1": [ZF]})
    run(f"[{i + 1}] 현재가 ZN+ZF 2종목", P + "price", {"Iccurs1": [ZN, ZF]})

today = f"{datetime.now():%Y%m%d}"
for i in range(3):
    run(f"[{i + 1}] 예수금 biz_dt={today}", P + "deposit", {"biz_dt": today, "cur_cd": "USD", "cvs_div": "1"})
    run(f"[{i + 1}] 예수금 biz_dt 빈 값", P + "deposit", {"biz_dt": "", "cur_cd": "USD", "cvs_div": "1"})
    run(f"[{i + 1}] 예수금 biz_dt 키 없음", P + "deposit", {"cur_cd": "USD", "cvs_div": "1"})
print("로그:", _nh.LOG_DIR)
