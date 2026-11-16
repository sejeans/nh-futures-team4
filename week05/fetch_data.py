# 5주차 데이터 수집: 10년 국채선물(KTB10)과 미국 10년 국채선물(ZN)의 일봉·1분봉을 받아 응답 원본을 results/ 에 저장한다
# 조회만 하고 주문은 하지 않는다. 클라이언트(토큰·호출 간격·재시도·로그)는 week02/nh.py, 해외 경로는 week03/nh_os.py 를 쓴다
#
# 차트 API 는 한 번에 받는 봉 수가 제한된다 (국내 일봉 9,999건, 국내 분봉 하루 단위, 해외 분봉 한 페이지 495봉).
# 그래서 나눠 받아 저장하고, load_* 함수가 여러 파일을 이어 붙인 뒤 시각 기준으로 중복을 지운다.
#
#   python fetch_data.py daily                       # KTB10·ZN 연결 일봉 전체
#   python fetch_data.py ktb 2026-11-13 2026-11-16   # KTB10 12월물 1분봉, 하루씩
#   python fetch_data.py zn 2026-10-29               # ZN 12월물 1분봉, 시작일부터 지금까지
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = HERE / "results"
sys.path.insert(0, str(ROOT / "week02"))
sys.path.insert(0, str(ROOT / "week03"))
import nh as _nh  # noqa: E402
import nh_os  # noqa: E402  (import 할 때 _nh.LOG_DIR 을 week03 으로 바꾸므로 아래에서 다시 지정한다)

_nh.LOG_DIR = RESULTS / "api_log"
KTB10 = "A676C000"  # 10년 국채선물 2026년 12월물 (week04, price 응답 2026-11-08)
ZN = nh_os.ZN       # ZNZ26, 미국 10년 국채선물 2026년 12월물
D = "/trade/v1/domestic/"

# 이전 주차에 받아 둔 분봉. 같은 월물이라 이어 붙여 쓴다
OLD_KTB_1M = sorted((ROOT / "week04" / "results").glob(f"bars_{KTB10}_1m_*.json"))
OLD_ZN_1M = [ROOT / "week03" / "results" / "bars_ZNZ26_1m_20260824_20261030.json"]


def _save(name, data):
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps({"called_at": datetime.now().isoformat(timespec="seconds"), "data": data},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", path.name, len(data), "건")
    return path


# ---------------------------------------------------------------- 수집
def ktb_daily(nh, exp_mod="0"):
    """국내 연결 일봉. nxt_key 를 따라가다 새 날짜가 안 나오면 멈춘다.
    11/16 첫 호출: req_qty 9999 로 1,192건(2021-12-27~)이 왔고 nxt_key 가 마지막 날짜(20211227)였다"""
    out, seen, key = [], set(), "99999999"
    for _ in range(20):
        r = nh.call(D + "chart-daily", {"nght_tp": "1", "sym": KTB10, "inq_strt_dt": "00000000",
                                        "inq_ed_dt": "99999999", "req_qty": "9999", "cidx_yn": "1",
                                        "nxt_key": key, "fut_cidx_exp_mod": exp_mod})
        new = [o for o in (r.get("Occurs1") or []) if o["occurs1_ref_dt"] not in seen]
        if not new:
            break
        out += new
        seen |= {o["occurs1_ref_dt"] for o in new}
        key = (r.get("nxt_key") or "").strip()
        if not key or set(key) <= {"9"}:
            break
    return out


def ktb_minute(nh, start, end):
    """국내 1분봉을 하루씩 받는다 (하루 약 411봉 < req_qty 2000). 실패한 날은 다시 시도"""
    recs, todo = [], list(pd.bdate_range(start, end).strftime("%Y%m%d"))
    for _ in range(3):
        failed = []
        for d in todo:
            body = {"nght_tp": "1", "sym": KTB10, "dcnt": "1", "req_qty": "2000", "inq_strt_dt": d, "inq_ed_dt": d}
            try:
                res = nh.call(D + "chart-minute", body)
            except _nh.NHError as e:
                failed.append(d)
                print(d, "실패:", e)
                continue
            recs += res.get("Occurs1") or []
        todo = failed
        if not todo:
            break
    return recs


def main(argv):
    what = argv[1]
    stamp = f"{datetime.now():%Y%m%d_%H%M}"
    if what == "daily":
        nh = _nh.NH()
        _save(f"daily_{KTB10}_cont_{stamp}.json", ktb_daily(nh, "0"))
        _save(f"daily_{KTB10}_cont_adj_{stamp}.json", ktb_daily(nh, "1"))   # 만기수정(월물 교체 갭 보정)
        _save(f"daily_ZN_cont_{stamp}.json", nh_os.NHOverseas().chart_daily(ZN, start="20000101", cidx="1"))
    elif what == "ktb":
        start, end = argv[2], argv[3]
        _save(f"bars_{KTB10}_1m_{start.replace('-', '')}_{end.replace('-', '')}_{stamp[-4:]}.json",
              ktb_minute(_nh.NH(), start, end))
    elif what == "zn":
        start = argv[2].replace("-", "")
        occ = nh_os.NHOverseas().chart_minute(ZN, dcnt=1, req_qty=9999, start=start, all_pages=True, max_pages=200)
        _save(f"bars_{ZN}_1m_{start}_{stamp}.json", occ)
    else:
        sys.exit(__doc__)


# ---------------------------------------------------------------- 읽기 (여러 파일 이어 붙이기 + 중복 제거)
PX = {"open_pric": "open", "high_pric": "high", "low_pric": "low", "close_pric": "close", "cum_trd_qty": "vol"}


def _occ(path):
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(rec, dict):
        return rec["data"]
    return [o for r in rec for o in (r["response"].get("Occurs1") or [])]  # week04 형식: 호출별 원본 목록


def _frame(occ, with_time):
    b = pd.DataFrame(occ).rename(columns=lambda c: c.removeprefix("occurs1_"))
    t = b.ref_dt + (b.exch_tm if with_time else "")
    b["t"] = pd.to_datetime(t, format="%Y%m%d%H%M%S" if with_time else "%Y%m%d")
    out = b.drop_duplicates("t", keep="last").set_index("t").sort_index()
    df = out[list(PX)].rename(columns=PX).astype(float)
    if "glb_biz_dt" in out:
        df["biz"] = pd.to_datetime(out.glb_biz_dt, format="%Y%m%d")
    return df


def _latest(pattern):
    files = sorted(RESULTS.glob(pattern))
    if not files:
        sys.exit(f"{pattern} 파일이 없다. python fetch_data.py daily 를 먼저 실행")
    return files[-1]


def load_daily(kind):
    """kind: 'ktb'(연결, 원가격) / 'ktb_adj'(만기수정) / 'zn'. 가장 최근 파일 하나를 읽는다"""
    pat = {"ktb": f"daily_{KTB10}_cont_2*.json", "ktb_adj": f"daily_{KTB10}_cont_adj_*.json",
           "zn": "daily_ZN_cont_*.json"}[kind]
    return _frame(_occ(_latest(pat)), False)


def load_minute(kind):
    """kind: 'ktb' / 'zn'. 이전 주차 파일과 이번 주 파일을 모두 이어 붙이고 시각이 같은 봉은 나중 파일 값을 남긴다.
    진행 중이던 봉(받은 시점의 마지막 봉)은 나중에 받은 완성본으로 덮인다"""
    files = (OLD_KTB_1M + sorted(RESULTS.glob(f"bars_{KTB10}_1m_*.json")) if kind == "ktb"
             else OLD_ZN_1M + sorted(RESULTS.glob(f"bars_{ZN}_1m_*.json")))
    occ = [o for f in files for o in _occ(f)]
    return _frame(occ, True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용법: fetch_data.py daily | ktb 시작일 종료일 | zn 시작일")
    main(sys.argv)
