# 해외 분봉·상품정보 수집: 응답 원본을 results/ 에 저장하고, 저장본을 DataFrame 으로 읽는다
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from nh_os import ZF, ZN, NHOverseas

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
COLS = {"open_pric": "open", "high_pric": "high", "low_pric": "low", "close_pric": "close", "cum_trd_qty": "vol"}


def save(name, data):
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps({"called_at": datetime.now().isoformat(timespec="seconds"), "data": data},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", path.name, len(data), "건")
    return path


def load(path):
    """저장된 chart-minute Occurs1 → 5분봉 DataFrame. 시각은 한국 시간, 봉 시작 시각 [가정 — README 2절]
    페이지가 겹쳐 같은 봉이 두 번 오므로 시각 기준으로 하나만 남긴다"""
    occ = json.loads(Path(path).read_text(encoding="utf-8"))["data"]
    b = (pd.DataFrame(occ)
         .rename(columns=lambda c: c.removeprefix("occurs1_"))
         .assign(t=lambda d: pd.to_datetime(d.ref_dt + d.exch_tm, format="%Y%m%d%H%M%S")))
    b = b.drop_duplicates("t").set_index("t").sort_index()
    out = b[list(COLS)].rename(columns=COLS).astype(float)
    out["biz"] = pd.to_datetime(b.glb_biz_dt, format="%Y%m%d")  # 해외영업일 (CME 거래일)
    return out


def main():
    nh = NHOverseas()
    today = f"{datetime.now():%Y%m%d}"
    save(f"specs_FG1_{today}.json", {"product_detail": nh.product_detail(), "market_operations": nh.market_operations()})
    for sym in (ZN, ZF):
        path = save(f"bars_{sym}_5m_{today}.json", nh.chart_minute(sym, dcnt=5, req_qty=9999, all_pages=True))
        b = load(path)
        n = b[b.index >= "2026-08-24"].groupby("biz").size()
        print(f"  {sym}: {b.index[0]} ~ {b.index[-1]}, 8/24 이후 영업일 {n.size}일, 하루 봉 수 {n.min()}~{n.max()} (중앙 {n.median():.0f})")
        print("  276봉(23시간) 미만인 날:", {f"{d:%m/%d}": c for d, c in n[n < 276].items()} or "없음")


if __name__ == "__main__":
    sys.exit(main())
