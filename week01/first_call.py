# first call
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URLS = {"paper": "https://apidemo.futures.co.kr", "real": "https://api.futures.co.kr"}
SYM = "A016C000"  # 코스피200 F 202612


def load_env(path):
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {url}\n{e.read().decode('utf-8', 'replace')}")


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
    print("토큰 발급 OK, 만료:", token.get("expires_at") or token.get("expires_in"))  # 토큰 값은 출력하지 않는다

    price = post(
        f"{base}/trade/v1/domestic/price",
        json.dumps({"sym": SYM}).encode(),
        {
            "Authorization": f"{token.get('token_type') or 'Bearer'} {token['access_token']}",
            "Content-Type": "application/json",
        },
    )
    out = Path(__file__).parent / "results" / "price_response.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(price, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(price, ensure_ascii=False, indent=2))
    print("응답 원본 저장:", out)


if __name__ == "__main__":
    main()
