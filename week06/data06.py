# 6주차 데이터: 코스닥150 선물 12월물(A066C000) 1분봉, 5분봉
# 2주차에 받아 둔 9/11~10/30 분봉에 11/02 이후 분봉을 더해 이어 붙인다. 조회만 하고 주문은 하지 않는다.
#   python data06.py 2026-11-02 2026-11-20   # 1분봉은 하루씩, 5분봉은 기간 한 번에 (하루 83봉, 2,000건 상한)
#   python data06.py                         # 저장본 점검만
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = HERE / "results"
sys.path.append(str(ROOT / "week02"))  # append: week06 파일 이름이 week02 것보다 먼저 잡히게
import nh as _nh  # noqa: E402
from fetch_bars import SYM, parse  # noqa: E402

_nh.LOG_DIR = RESULTS / "api_log"
W2 = ROOT / "week02" / "results"
FULL_DAY = {1: 411, 5: 83}  # 08:45~15:45 정상 거래일 봉 수 (2주차 fetch_bars.py 점검 기준)


def fetch(start, end):
    nh = _nh.NH()
    path = "/trade/v1/domestic/chart-minute"
    s, e = start.replace("-", ""), end.replace("-", "")
    recs = []
    for d in pd.bdate_range(start, end).strftime("%Y%m%d"):
        body = {"nght_tp": "1", "sym": SYM, "req_qty": "2000", "dcnt": "1", "inq_strt_dt": d, "inq_ed_dt": d}
        recs.append({"request": body, "response": nh.call(path, body)})
    _save(f"bars_{SYM}_1m_{s}_{e}.json", recs)
    body = {"nght_tp": "1", "sym": SYM, "req_qty": "2000", "dcnt": "5", "inq_strt_dt": s, "inq_ed_dt": e}
    _save(f"bars_{SYM}_5m_{s}_{e}.json", [{"request": body, "response": nh.call(path, body)}])


def _save(name, recs):
    RESULTS.mkdir(exist_ok=True)
    for r in recs:
        r["called_at"] = datetime.now().isoformat(timespec="seconds")
    (RESULTS / name).write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")
    print("저장:", name)


def _read(path, minutes):
    rec = json.loads(path.read_text(encoding="utf-8"))
    occ = [o for r in (rec if isinstance(rec, list) else [rec]) for o in (r["response"].get("Occurs1") or [])]
    return parse(occ, minutes) if occ else None


def load(minutes):
    """2주차 저장본과 6주차 저장본을 이어 붙인다. 같은 시각 봉은 나중에 받은 파일 값을 남긴다"""
    files = sorted(W2.glob(f"bars_{SYM}_{minutes}m_*.json")) + sorted(RESULTS.glob(f"bars_{SYM}_{minutes}m_*.json"))
    b = pd.concat([x for x in (_read(f, minutes) for f in files) if x is not None])
    b = b[~b.index.duplicated(keep="last")].sort_index()
    return b[b.index.strftime("%H:%M") <= "15:45"]


def check():
    for m in (1, 5):
        n = load(m).groupby("day").size()
        short = n[n != FULL_DAY[m]]
        print(f"{m}분봉: {n.size}일 {n.sum()}봉 {n.index[0]:%m/%d}~{n.index[-1]:%m/%d}, "
              f"{FULL_DAY[m]}봉 아닌 날 {dict(zip(short.index.strftime('%m/%d'), short)) or '없음'}")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        fetch(sys.argv[1], sys.argv[2])
    check()
