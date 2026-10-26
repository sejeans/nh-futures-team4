# 분봉 수집: chart-minute 응답 원본을 results/ 에 저장하고, 저장본을 DataFrame 으로 읽는다
import json
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "week01"))
from first_call import BASE_URLS, load_env, post  # noqa: E402

SYM = "A066C000"  # 코스닥150 F 202612
RESULTS = HERE / "results"
BARS_1M = RESULTS / f"bars_{SYM}_1m_20260911_20261023.json"
BARS_5M = [RESULTS / f"bars_{SYM}_5m_20260911_20261009.json",  # 선택 구간 (params_bollinger.ipynb 가 받음)
           RESULTS / f"bars_{SYM}_5m_20261012_20261023.json"]  # 검증 구간
COLS = {"open_pric": "open", "high_pric": "high", "low_pric": "low", "close_pric": "close", "opint": "oi"}


def chart_client():
    env = load_env(ROOT / ".env")
    base = BASE_URLS[env.get("NH_ENV", "paper")]
    token = post(
        f"{base}/auth-service/v1/token",
        urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "appkey": env["NH_DOMESTIC_APP_KEY"],
            "appsecret": env["NH_DOMESTIC_APP_SECRET"],
        }).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    headers = {
        "Authorization": f"{token.get('token_type') or 'Bearer'} {token['access_token']}",
        "Content-Type": "application/json",
    }
    path = "/trade/v1/domestic/chart-minute"

    def chart(**kw):
        body = {"nght_tp": "1", "sym": SYM, "req_qty": "2000", **kw}
        res = post(f"{base}{path}", json.dumps(body).encode(), headers)
        time.sleep(0.2)  # 시세 10회/초 제한
        return {"called_at": datetime.now().isoformat(timespec="seconds"), "server": base,
                "path": path, "request": body, "response": res}

    return chart


def load(path, minutes):
    """저장된 응답(한 건 또는 목록) → 봉 DataFrame"""
    rec = json.loads(path.read_text(encoding="utf-8"))
    return parse([o for r in (rec if isinstance(rec, list) else [rec]) for o in (r["response"].get("Occurs1") or [])], minutes)


def parse(occ, minutes):
    """chart-minute Occurs1 → 봉 DataFrame. 표기 시각 = 봉 시작 시각 (params_bollinger.ipynb 1-1)"""
    b = (pd.DataFrame(occ)
         .rename(columns=lambda c: c.removeprefix("occurs1_"))
         .assign(t=lambda d: pd.to_datetime(d.ref_dt + d.exch_tm, format="%Y%m%d%H%M%S"))
         .set_index("t").sort_index()[list(COLS)].rename(columns=COLS).astype(float))
    b["day"] = b.index.normalize()
    b["auction"] = b.index.strftime("%H:%M") == "15:45"   # 종료 단일가
    b["close_t"] = b.index + pd.Timedelta(minutes=minutes)
    return b


def main():
    chart = None
    if not BARS_1M.exists():
        chart = chart_client()
        days = pd.bdate_range("2026-09-11", "2026-10-23").strftime("%Y%m%d")
        recs = [chart(dcnt="1", inq_strt_dt=d, inq_ed_dt=d) for d in days]  # 하루 411봉 < 2000건 상한
        BARS_1M.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", BARS_1M.name)
    if not BARS_5M[1].exists():
        chart = chart or chart_client()
        rec = chart(dcnt="5", inq_strt_dt="20261012", inq_ed_dt="20261023")
        BARS_5M[1].write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", BARS_5M[1].name)

    for path, minutes, full in [(BARS_1M, 1, 411), (BARS_5M[0], 5, 83), (BARS_5M[1], 5, 83)]:
        n = load(path, minutes).groupby("day").size()
        short = n[n != full]
        print(f"{path.name}: {n.size}일 {n.sum()}봉, {n.index[0]:%m/%d}~{n.index[-1]:%m/%d}, "
              f"{full}봉 아닌 날 {dict(zip(short.index.strftime('%m/%d'), short)) or '없음'}")


if __name__ == "__main__":
    main()
