# 4주차 분봉 수집: 3년·10년 국채선물 1분봉을 하루씩 받아 응답 원본을 results/ 에 저장한다 (조회만, 주문 없음)
# 클라이언트(토큰·호출 간격·재시도·로그)는 week02/nh.py, 봉 파싱은 week02/fetch_bars.py 의 parse 를 그대로 쓴다
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "week02"))
import nh as _nh  # noqa: E402

# 이 파일과 이름이 같아서 import 문으로는 못 부른다 → 경로로 읽는다
_spec = importlib.util.spec_from_file_location("week02_fetch_bars", HERE.parent / "week02" / "fetch_bars.py")
_w2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_w2)
parse = _w2.parse

_nh.LOG_DIR = HERE / "results" / "api_log"
RESULTS = HERE / "results"
KTB3, KTB10 = "A656C000", "A676C000"  # 3년·10년 국채선물 2026년 12월물 (price 응답 sym_nm, 2026-11-08)


def fetch(sym, start, end):
    nh = _nh.NH()
    recs, todo = [], list(pd.bdate_range(start, end).strftime("%Y%m%d"))
    for _ in range(3):  # 11/09 장중 타임아웃이 잦아서, 실패한 날은 건너뛰었다가 다시 받는다
        failed = []
        for d in todo:
            body = {"nght_tp": "1", "sym": sym, "dcnt": "1", "req_qty": "2000", "inq_strt_dt": d, "inq_ed_dt": d}
            try:
                res = nh.call("/trade/v1/domestic/chart-minute", body)
            except _nh.NHError as e:
                failed.append(d)
                print(sym, d, "실패:", e)
                continue
            recs.append({"called_at": datetime.now().isoformat(timespec="seconds"), "request": body, "response": res})
        todo = failed
        if not todo:
            break
    if todo:
        print(sym, "끝내 못 받은 날:", todo)
    if not recs:  # 11/10: 하루도 못 받았는데 빈 파일을 저장해, 재시작할 때마다 load 에서 죽고 다시 받지 못했다
        sys.exit(f"{sym} {start}~{end} 분봉을 하루도 못 받음. 파일을 저장하지 않고 종료")
    recs.sort(key=lambda r: r["request"]["inq_strt_dt"])
    path = RESULTS / f"bars_{sym}_1m_{start.replace('-', '')}_{end.replace('-', '')}.json"
    RESULTS.mkdir(exist_ok=True)
    path.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(path):
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse([o for r in rec for o in (r["response"].get("Occurs1") or [])], 1)


if __name__ == "__main__":
    start, end = sys.argv[1], sys.argv[2]  # 예: 2026-09-11 2026-11-09
    for sym in (KTB3, KTB10):
        p = fetch(sym, start, end)
        n = load(p).groupby("day").size()
        print(f"{p.name}: {n.size}일 {n.sum()}봉, 하루 봉 수 {n.value_counts().to_dict()}")
