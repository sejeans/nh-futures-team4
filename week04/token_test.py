# 7절 오류 1번(401 EGW023/EGW052) 원인 확인: 같은 키로 토큰을 다시 받으면 무엇이 오는가
# 토큰 A 발급 → A로 시세 1회 → 토큰 B 발급 → A로 시세 1회 → B로 시세 1회. 재시도 없이 첫 응답만 본다.
# 11/11 17:30 이 PC 결과: A와 B가 같은 토큰, expires_at 은 처음 발급 시각 + 24시간 그대로, expires_in 은 늘 "86400".
# 다른 PC에서도 돌려 expires_at 을 비교하면 토큰이 PC(IP)마다 따로인지 알 수 있다.
# 시세 조회만 하고 주문은 없다. 같은 국내 키를 쓰는 live.py 가 돌지 않을 때(15:30 이후, 08:50 이전)만 실행한다.
import json
import socket
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "week02"))
import nh  # noqa: E402

nh.LOG_DIR = HERE / "results" / "api_log"
PATH, BODY = "/trade/v1/domestic/price", {"sym": "A676C000"}


def issue(c, label, out):
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "appkey": c._key, "appsecret": c._secret}).encode()
    status, res, _ = c._http("/auth-service/v1/token", body, {"Content-Type": "application/x-www-form-urlencoded"}, "auth")
    row = {"step": label, "at": datetime.now().isoformat(timespec="milliseconds"), "status": status,
           "expires_in": res.get("expires_in"), "expires_at": res.get("expires_at")}  # 토큰 문자열은 남기지 않는다
    out.append(row)
    print(row)
    return f"{res.get('token_type') or 'Bearer'} {res['access_token']}"


def hit(c, token, label, out):
    status, res, elapsed = c._http(PATH, json.dumps(BODY).encode(),
                                   {"Authorization": token, "Content-Type": "application/json"}, "quote")
    c._log(PATH, BODY, status, res, elapsed, 0)
    row = {"step": label, "at": datetime.now().isoformat(timespec="milliseconds"), "status": status,
           "code": res.get("errorCode"), "msg": res.get("errorMessage")}
    out.append(row)
    print(row)


def main():
    c, out = nh.NH(), [{"host": socket.gethostname()}]
    a = issue(c, "A 발급", out)
    hit(c, a, "A로 조회", out)
    b = issue(c, "B 발급", out)
    out.append({"step": "A와 B가 같은 토큰인가", "same": a == b})
    print(out[-1])
    hit(c, a, "B 발급 후, A로 조회", out)
    hit(c, b, "B 발급 후, B로 조회", out)
    f = HERE / "results" / f"token_test_{datetime.now():%Y%m%d_%H%M%S}_{socket.gethostname()}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장:", f.name)


if __name__ == "__main__":
    main()
