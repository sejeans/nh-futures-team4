# 오류 제보 2 재현: product-detail 주간 품목의 틱가치·거래승수 0, 만기일·증거금 빈값
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "week01"))
from first_call import BASE_URLS, load_env, post  # noqa: E402

OUT = Path(__file__).parent / "results" / "error_reports"
EMPTY = ("occurs1_exp_dt", "occurs1_init_mrgn", "occurs1_mtn_mrgn", "occurs1_ctr_init_mrgn")


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

    rows = call("/trade/v1/domestic/product-detail", {}, "product_detail").get("Occurs1") or []
    # 명세의 「야간 모의 환경 미지원」은 야간 품목만 해당하므로 주간 품목만 센다
    day = [r for r in rows if not r["occurs1_dtl_cd_ko_nm"].startswith("(야간)")]
    zero = [r for r in day if float(r["occurs1_mltplr"] or 0) == 0 and float(r["occurs1_tick_val"] or 0) == 0]
    blank = [r for r in day if not any(r[k] for k in EMPTY)]
    print(f"[product-detail] {stamp} 주간 품목 {len(day)}개 중 승수·틱가치 0: {len(zero)}개, 만기일·증거금 빈값: {len(blank)}개")
    for sym in ["A066C000", "A016C000"]:
        p = call("/trade/v1/domestic/price", {"sym": sym}, f"price_{sym}")
        print(f"[price] {sym} mltplr={p.get('mltplr')}")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
