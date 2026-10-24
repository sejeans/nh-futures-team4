# 오류 제보 재현: chart-minute req_qty 상한
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "week01"))
from first_call import BASE_URLS, load_env, post  # noqa: E402

SYM = "A066C000"  # 코스닥150 F 202612
OUT = Path(__file__).parent / "results" / "error_reports"


def main():
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
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def call(path, body, name):
        res = post(f"{base}{path}", json.dumps(body).encode(), headers)
        rec = {"called_at": datetime.now().isoformat(timespec="seconds"), "server": base,
               "path": path, "request": body, "response": res}
        (OUT / f"{name}_{stamp}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return res

    # chart-minute: 명세 "기본 300건 (최대 9999건)"
    print("[chart-minute] req_qty -> nrec / len(Occurs1)")
    for q in [None, "1000", "2000", "2001", "3000", "9999"]:
        body = {"nght_tp": "1", "sym": SYM, "dcnt": "1"}
        if q:
            body["req_qty"] = q
        res = call("/trade/v1/domestic/chart-minute", body, f"chart_minute_req{q or 'default'}")
        print(f"  {q or '(생략)':>6} -> {res.get('nrec')} / {len(res.get('Occurs1') or [])}")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
