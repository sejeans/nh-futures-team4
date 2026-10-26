# NH선물 REST API 클라이언트 — 토큰 재사용 · 호출 간격 · 재시도 · 응답 로그 · 실주문 차단
# 1주차 first_call.py 의 load_env·BASE_URLS 를 이어 쓴다
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "week01"))
from first_call import BASE_URLS, load_env  # noqa: E402

LOG_DIR = HERE / "results" / "api_log"
TIMEOUT = 10
RETRIES = 3
BACKOFF = [0.5, 1, 2, 4]
MIN_GAP = {"quote": 0.1, "account": 0.1, "order": 0.2, "auth": 0.34}  # 초당 시세 10·계좌 10·주문 5·인증 3 (운영안내 17p)
ORDER_PATHS = {"order", "modify", "cancel", "order-night", "modify-night", "cancel-night"}
ACCOUNT_PATHS = {"deposit", "open-interest", "order-history", "order-error", "orderable-quantity"}
RATE_CODES = {"EGW020", "EGW036"}   # 허용량·속도 초과 (운영안내 22p)
TOKEN_CODES = {"EGW018", "EGW052"}  # 토큰 만료
MASK_SUFFIX = ("ac_no", "ac_nm", "user_ip_addr")  # 로그에 남기지 않는다 (계획 5-3)
SYM = "A066C000"  # 코스닥150 F 202612
BAL_SIDE = {"1": 1, "2": -1}  # 잔고 trd_div 도 주문처럼 1 매수·2 매도라고 가정 [10/26 manual_roundtrip.py 로 확인]


class NHError(Exception):
    pass


class OrderUnknown(NHError):
    """주문 응답을 못 받음. 체결됐을 수도 있으니 재주문 전에 order_history·open_interest 를 먼저 본다 (운영안내 22p)"""


def _kind(path):
    seg = path.rstrip("/").rsplit("/", 1)[-1]
    return "order" if seg in ORDER_PATHS else "account" if seg in ACCOUNT_PATHS else "quote"


def _mask(x):
    if isinstance(x, dict):
        return {k: "***" if k.endswith(MASK_SUFFIX) else _mask(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_mask(v) for v in x]
    return x


def _codes(res):
    text = json.dumps(res, ensure_ascii=False)
    return {c for c in RATE_CODES | TOKEN_CODES if c in text}


class NH:
    def __init__(self, env_file=ROOT / ".env"):
        env = load_env(env_file)
        self.env = env.get("NH_ENV", "paper")
        self.base = BASE_URLS[self.env]
        self._key, self._secret = env["NH_DOMESTIC_APP_KEY"], env["NH_DOMESTIC_APP_SECRET"]
        self._token, self._token_until = None, 0.0
        self._last = {}

    def _http(self, path, data, headers, kind):
        gap = MIN_GAP[kind] - (time.monotonic() - self._last.get(kind, 0.0))
        if gap > 0:
            time.sleep(gap)
        self._last[kind] = time.monotonic()
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status, text = r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode("utf-8", "replace")
        try:
            res = json.loads(text)
        except ValueError:
            res = {"_raw": text[:500]}
        return status, res, round(time.monotonic() - t0, 3)

    def _auth(self):
        body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "appkey": self._key, "appsecret": self._secret}).encode()
        status, res, _ = self._http("/auth-service/v1/token", body,
                                    {"Content-Type": "application/x-www-form-urlencoded"}, "auth")
        if status != 200 or "access_token" not in res:
            raise NHError(f"토큰 발급 실패 HTTP {status} {_codes(res) or ''}")  # 응답 본문은 찍지 않는다
        self._token = f"{res.get('token_type') or 'Bearer'} {res['access_token']}"
        # ponytail: expires_in 이 없으면 만료 오류코드를 받을 때만 재발급
        self._token_until = time.monotonic() + int(res["expires_in"]) - 60 if res.get("expires_in") else float("inf")

    def _log(self, path, body, status, res, elapsed, attempt):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().isoformat(timespec="milliseconds"), "env": self.env, "path": path,
               "request": body, "status": status, "elapsed": elapsed, "attempt": attempt, "response": _mask(res)}
        with open(LOG_DIR / f"{datetime.now():%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def call(self, path, body):
        kind = _kind(path)
        if kind == "order" and (self.env != "paper" or self.base != BASE_URLS["paper"]):
            raise NHError("주문은 모의(NH_ENV=paper)에서만 보낸다")
        for attempt in range(RETRIES + 1):
            if self._token is None or time.monotonic() > self._token_until:
                self._auth()
            headers = {"Authorization": self._token, "Content-Type": "application/json"}
            try:
                status, res, elapsed = self._http(path, json.dumps(body).encode(), headers, kind)
            except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
                self._log(path, body, None, {"_error": repr(e)}, None, attempt)
                if kind == "order":
                    raise OrderUnknown(f"주문 응답 없음 ({e!r})") from e
                time.sleep(BACKOFF[attempt])
                continue
            self._log(path, body, status, res, elapsed, attempt)
            codes = _codes(res)
            if codes & TOKEN_CODES:          # 게이트웨이에서 막힌 요청이라 주문도 재전송해도 된다
                self._token = None
                continue
            if codes & RATE_CODES or status == 429:
                time.sleep(BACKOFF[attempt])
                continue
            if status >= 500:
                if kind == "order":
                    raise OrderUnknown(f"주문 HTTP {status}")
                time.sleep(BACKOFF[attempt])
                continue
            if status != 200:
                raise NHError(f"HTTP {status} {path} {res.get('errorCode') or res.get('msg_cd', '')} "
                              f"{res.get('errorMessage') or res.get('msg_cntn', '')}".strip())
            return res
        raise NHError(f"{path}: {RETRIES}회 재시도 후 실패")

    # --- 시세 ---
    def price(self, sym=SYM):
        return self.call("/trade/v1/domestic/price", {"sym": sym})

    def price_bid(self, sym=SYM):
        return self.call("/trade/v1/domestic/price-bid", {"exch_cd": "KSP", "sym": sym})

    def chart_minute(self, sym=SYM, dcnt=5, req_qty=40):
        return self.call("/trade/v1/domestic/chart-minute",
                         {"nght_tp": "1", "sym": sym, "dcnt": str(dcnt), "req_qty": str(req_qty)})

    def trend_investor(self, opt_prd="061", ref_dt=None):
        # opt_prd = 품목코드(06: KOSDAQ, price-all-futures 명세) + 선물(1). 10/23 조회로 값 나옴 확인 (10/25)
        return self.call("/trade/v1/domestic/trend-investor",
                         {"opt_prd": opt_prd, "ref_dt": ref_dt or f"{datetime.now():%Y%m%d}", "inq_tp": "1"})

    # --- 계좌 ---
    # ponytail: nxt_key 이어받기 없음. 하루 주문 수십 건이면 한 번에 온다 [추정]
    def deposit(self, biz_dt=None):  # 영업일이어야 값이 나온다 (일요일 조회는 전부 0, 10/25 확인)
        return self.call("/trade/v1/domestic/deposit", {"biz_dt": biz_dt or f"{datetime.now():%Y%m%d}"})

    def open_interest(self):
        return self.call("/trade/v1/domestic/open-interest", {"nxt_key": ""})

    def order_history(self):
        return self.call("/trade/v1/domestic/order-history",
                         {"trd_div": "0", "exec_div": "0", "trd_tm_div_cd": "0", "ord_div_cd": "0", "nxt_key": ""})

    def position(self, sym=SYM):
        """잔고 기준 순포지션(+매수/-매도 계약 수)과 평균가. 주문 결과·재시작 판단은 이 값을 기준으로 한다"""
        rows = [r for r in self.open_interest().get("Occurs1") or [] if r.get("occurs1_sym", "").strip() == sym]
        pos = sum(BAL_SIDE[r["occurs1_trd_div"].strip()] * int(float(r["occurs1_opint_qty"])) for r in rows)
        return pos, (float(rows[0]["occurs1_avg_pric"]) if rows else None)

    def find_fill(self, ord_no, tries=5):
        """주문내역에서 체결(또는 거부)을 찾는다. 못 찾으면 None"""
        key = str(ord_no).strip().lstrip("0")
        for _ in range(tries):
            for r in self.order_history().get("Occurs1") or []:
                if r.get("occurs1_ord_no", "").strip().lstrip("0") != key:
                    continue
                qty = float(r.get("occurs1_exec_qty") or 0)
                reject = (r.get("occurs1_ord_rejt_rsn") or "").strip()
                if qty > 0 or reject:
                    px = float(r.get("occurs1_avg_exec_pric") or 0) or float(r.get("occurs1_exec_pric") or 0)
                    return {"qty": qty, "px": px or None, "status": r.get("occurs1_ord_sts_nm"),
                            "time": r.get("occurs1_exch_exec_tm"), "reject": reject}
            time.sleep(1)
        return None

    # --- 주문 ---
    def order(self, side, qty=1, sym=SYM, exec_cnd="1"):
        """시장가 신규주문. side +1 매수 / -1 매도. exec_cnd 1=FAS
        (시장가는 FOK·FAK 둘 다 거부 5039 — 10/26 실측. 운영안내 22p 는 FOK 만 적혀 있음)"""
        res = self.call("/trade/v1/domestic/order", {
            "sym": sym, "trd_div": "1" if side > 0 else "2", "ord_tp_cd": "2",
            "ord_qty": str(qty), "ord_pric": "0", "exec_cnd_cd": exec_cnd})
        if not str(res.get("ord_no", "")).strip():
            raise NHError(f"주문 거부 {res.get('msg_cd')} {res.get('msg_cntn')}")
        return res


def selfcheck():
    assert _kind("/trade/v1/domestic/order") == "order"
    assert _kind("/trade/v1/domestic/order-history") == "account"
    assert _kind("/trade/v1/domestic/price") == "quote"
    m = _mask({"Occurs1": [{"occurs1_ac_no": "123", "occurs1_ac_nm": "홍", "occurs1_user_ip_addr": "1.2.3.4", "sym": "A"}]})
    assert m == {"Occurs1": [{"occurs1_ac_no": "***", "occurs1_ac_nm": "***", "occurs1_user_ip_addr": "***", "sym": "A"}]}
    assert _codes({"rsp_cd": "EGW020"}) == {"EGW020"}


if __name__ == "__main__":
    # 조회만 한다. 주문은 보내지 않는다
    selfcheck()
    nh = NH()
    print("환경:", nh.env, nh.base)
    p = nh.price()
    print("price:", p.get("sym_nm"), p.get("last_pric"))
    b = nh.price_bid()["Occurs1"][0]
    print("price_bid: 매도1", b["occurs1_ask_best_pric"], "/ 매수1", b["occurs1_bid_best_pric"])
    c = nh.chart_minute()
    print("chart_minute(5분):", c.get("nrec"), "봉")
    d = nh.deposit()
    print("deposit: 수수료", d.get("fee"), "/ 주문가능", d.get("ord_psb_tot_amt"))
    print("open_interest:", nh.open_interest().get("nrec"), "건")
    print("order_history:", nh.order_history().get("nrec"), "건")
    t = nh.trend_investor()
    print("trend_investor: 외국인 순매수", t.get("frgn_net_buy"))
    print("토큰 만료 정보:", "expires_in 있음" if nh._token_until != float("inf") else "없음 (오류코드로만 재발급)")
    print("로그:", LOG_DIR / f"{datetime.now():%Y%m%d}.jsonl")
