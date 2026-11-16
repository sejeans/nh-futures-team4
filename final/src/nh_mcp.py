# NH선물 REST API MCP 서버 — LLM(Claude 등)이 시세·계좌 조회와 모의 주문을 도구로 호출한다
#   실행: .venv/Scripts/python.exe final/src/nh_mcp.py   (stdio. 보통은 .mcp.json 을 통해 MCP 클라이언트가 띄운다)
#   점검: .venv/Scripts/python.exe final/src/nh_mcp.py --selfcheck   (API 호출 없이 한도 검사 로직만 시험)
# API 호출은 2주차 nh.py(토큰 재사용·호출 간격·재시도·응답 로그·실주문 차단)와 3주차 nh_os.py 를 그대로 쓴다.
# MCP 규격·SDK: https://modelcontextprotocol.io , https://github.com/modelcontextprotocol/python-sdk (MCPServer 예제 참고)
#
# 주문 안전장치 (LLM 이 잘못 판단해도 서버가 막는다)
#   1) 모의 서버만: nh.py 의 call() 이 NH_ENV=paper 가 아니면 주문 경로를 거부한다
#   2) 2단계 주문: preview_order 가 한도를 검사하고 주문표(ticket)를 만든다 → submit_order(ticket_id) 만 실제로 보낸다.
#      주문표는 TICKET_TTL 초 뒤 만료, 1회용
#   3) 한도(limits.json): 허용 종목, 주문당 수량, 종목별 순포지션, 하루 주문 건수, 지정가의 현재가 대비 괴리
#   4) 정지 스위치: final/results/HALT 파일이 있으면 신규 주문을 전부 거부한다. halt_trading 도구로 만들 수 있고 지우는 것은 사람만
#   5) 기록: 미리보기·주문·체결 결과를 final/results/orders_YYYYMMDD.jsonl 에, API 응답 원본을 final/results/api_log/ 에 남긴다
#   6) 주문 응답을 못 받으면(OrderUnknown) 재주문하지 않고 잔고를 조회해 돌려준다 (운영안내 22p: 재주문 전 주문내역·잔고 확인)
# stdio 서버는 stdout 이 프로토콜 통로다. 이 파일과 nh.py 는 print 를 쓰지 않는다.
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "week02"))
sys.path.insert(0, str(ROOT / "week03"))
import nh as _nh  # noqa: E402
import nh_os  # noqa: E402  (import 하면서 _nh.MASK_SUFFIX 를 해외 필드까지 넓힌다)

RESULTS = HERE.parent / "results"
_nh.LOG_DIR = RESULTS / "api_log"
HALT = RESULTS / "HALT"
LIMITS_FILE = HERE / "limits.json"
TICKET_TTL = 120
D, O = "/trade/v1/domestic/", "/trade/v1/overseas/"

# 종목 정보. 출처: 모의 서버 price·product-detail 응답 (CLAUDE.md 2~4주차 조회 기록, week03/results/specs_FG1_20261101.json)
# mult = 가격 1.0 의 금액(해당 통화). KTB 틱 0.01 = 10,000원, ZN 틱 1/64 = $15.625
SYMBOLS = {
    "A656C000": {"name": "3년 국채선물 2026년 12월물", "alias": ["KTB3", "3년", "3년물"], "market": "domestic",
                 "tick": 0.01, "mult": 1_000_000, "cur": "KRW"},
    "A676C000": {"name": "10년 국채선물 2026년 12월물", "alias": ["KTB10", "10년", "10년물"], "market": "domestic",
                 "tick": 0.01, "mult": 1_000_000, "cur": "KRW"},
    "A066C000": {"name": "코스닥150 선물 2026년 12월물", "alias": ["KQ150", "코스닥150"], "market": "domestic",
                 "tick": 0.1, "mult": 10_000, "cur": "KRW"},
    "ZNZ26": {"name": "미국 10년 국채선물(CME) 2026년 12월물", "alias": ["ZN"], "market": "overseas",
              "tick": 0.015625, "mult": 1_000, "cur": "USD"},
    "ZFZ26": {"name": "미국 5년 국채선물(CME) 2026년 12월물", "alias": ["ZF"], "market": "overseas",
              "tick": 0.0078125, "mult": 1_000, "cur": "USD"},
}
KTB_FEE_RATE = 0.0000329  # 국채선물 편도 수수료 = 거래대금의 0.00329% (4주차 11/09 수동 왕복 실측). 다른 종목은 추정하지 않는다

_clients, _tickets = {}, {}


def client(market):
    if market not in _clients:
        _clients[market] = _nh.NH() if market == "domestic" else nh_os.NHOverseas()
    return _clients[market]


def num(x):
    """'000000000100000000.000' 같은 고정폭 문자열 → float. 빈 값은 None"""
    try:
        return float(str(x).strip())
    except ValueError:
        return None


def spec(symbol):
    s = symbol.strip().upper()
    for code, v in SYMBOLS.items():
        if s == code or s in (a.upper() for a in v["alias"]):
            return code, v
    raise ValueError(f"등록되지 않은 종목 {symbol}. list_symbols 로 확인")


def limits():
    return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))  # 호출할 때마다 읽는다: 고치면 재시작 없이 반영


def journal(event, **rec):
    RESULTS.mkdir(parents=True, exist_ok=True)
    rec = {"t": datetime.now().isoformat(timespec="seconds"), "event": event, **rec}
    with open(RESULTS / f"orders_{datetime.now():%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(_nh._mask(rec), ensure_ascii=False, default=str) + "\n")


def sent_today():
    p = RESULTS / f"orders_{datetime.now():%Y%m%d}.jsonl"
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text(encoding="utf-8").splitlines() if json.loads(line)["event"] == "주문 전송")


# ---------- 조회 (내부) ----------
def quote(code):
    v = SYMBOLS[code]
    if v["market"] == "domestic":
        p = client("domestic").price(code)
        return {"symbol": code, "name": v["name"], "last": num(p["last_pric"]), "bid": num(p["bid_pric"]),
                "ask": num(p["ask_pric"]), "open": num(p["open_pric"]), "high": num(p["high_pric"]),
                "low": num(p["low_pric"]), "prev_settle": num(p["pd_sett_pric"]), "volume": num(p["trd_qty"]),
                "days_to_expiry": num(p["rem_dy"]), "currency": "KRW"}
    p = client("overseas").price(code)
    g = lambda k: num(p.get("occurs1_" + k))  # noqa: E731
    return {"symbol": code, "name": v["name"], "last": g("last_pric"), "bid": g("bid_pric"), "ask": g("ask_pric"),
            "open": g("open_pric"), "high": g("high_pric"), "low": g("low_pric"), "prev_settle": g("sett_pric"),
            "volume": g("cum_trd_qty"), "quote_time_kst": p.get("occurs1_trd_tm"), "currency": "USD"}


def positions(market):
    """{종목코드: {"qty": 순포지션(+매수/-매도), "avg": 평균가, "unrealized": 평가손익 또는 None}}"""
    # TODO: 국내 open_interest·order_history 는 첫 페이지만 읽는다(week02/nh.py). 다음 페이지까지 읽고,
    #       못 읽으면 결과 미확인으로 처리할 것. team-09 제보(11/16) 참고. 최종프로젝트_아이디어.md "수정할 사항"
    out = {}
    if market == "domestic":
        for r in client(market).open_interest().get("Occurs1") or []:
            sym = r["occurs1_sym"].strip()
            q = _nh.BAL_SIDE[r["occurs1_trd_div"].strip()] * int(num(r["occurs1_opint_qty"]))
            out[sym] = {"qty": out.get(sym, {}).get("qty", 0) + q, "avg": num(r.get("occurs1_avg_pric")),
                        "unrealized": num(r.get("occurs1_pl_amt", ""))}
    else:
        for r in client(market).open_interest():
            sym = r["occurs1_sym"].strip()
            q = {"1": 1, "2": -1}[r["occurs1_trd_tp"].strip()] * int(num(r["occurs1_opint_qty"]))
            out[sym] = {"qty": out.get(sym, {}).get("qty", 0) + q, "avg": num(r.get("occurs1_avg_pric")),
                        "unrealized": num(r.get("occurs1_pl_amt", ""))}
    return out


# ---------- 한도 검사 (API 호출 없음. selfcheck 로 시험) ----------
def check_leg(leg, q, pos_qty, lim):
    """한 주문(leg)이 한도 안인지 검사한다. 위반 사유 목록을 돌려준다 (비어 있으면 통과)"""
    code, v = spec(leg["symbol"])
    bad = []
    if code not in lim["allowed_symbols"]:
        bad.append(f"{code} 는 허용 종목이 아님")
    if code in lim.get("blocked_symbols", {}):
        bad.append(f"{code} 주문 차단: {lim['blocked_symbols'][code]}")
    if leg["side"] not in ("buy", "sell"):
        bad.append("side 는 buy 또는 sell")
    if not isinstance(leg["qty"], int) or leg["qty"] < 1:
        bad.append("qty 는 1 이상 정수")
    elif leg["qty"] > lim["max_qty_per_order"]:
        bad.append(f"수량 {leg['qty']} > 주문당 한도 {lim['max_qty_per_order']}")
    else:
        after = pos_qty + (leg["qty"] if leg["side"] == "buy" else -leg["qty"])
        # 포지션을 줄이는 주문은 한도를 넘은 상태에서도 허용한다 (청산을 막지 않기 위해)
        if abs(after) > lim["max_position_per_symbol"] and abs(after) > abs(pos_qty):
            bad.append(f"주문 후 순포지션 {after:+d} 가 종목별 한도 ±{lim['max_position_per_symbol']} 초과")
    if leg["type"] not in ("market", "limit"):
        bad.append("type 은 market 또는 limit")
    elif leg["type"] == "limit":
        px = leg.get("price")
        if not px or px <= 0:
            bad.append("지정가 주문은 price 필요")
        else:
            if abs(px / v["tick"] - round(px / v["tick"])) > 1e-6:
                bad.append(f"가격 {px} 이 호가 단위 {v['tick']} 의 배수가 아님")
            if q.get("last") and abs(px / q["last"] - 1) * 100 > lim["max_limit_deviation_pct"]:
                bad.append(f"지정가 {px} 가 현재가 {q['last']} 에서 {lim['max_limit_deviation_pct']}% 넘게 벗어남")
    return bad


def selfcheck():
    lim = {"allowed_symbols": ["A656C000", "A676C000"], "blocked_symbols": {"A676C000": "시험"}, "max_qty_per_order": 3,
           "max_position_per_symbol": 5, "max_orders_per_day": 20, "max_limit_deviation_pct": 0.5}
    q = {"last": 103.43}
    leg = lambda **k: {"symbol": "KTB3", "side": "buy", "qty": 1, "type": "market", **k}  # noqa: E731
    assert check_leg(leg(), q, 0, lim) == []
    assert check_leg(leg(qty=4), q, 0, lim)                      # 주문당 수량 초과
    assert check_leg(leg(qty=2), q, 4, lim)                      # 순포지션 한도 초과
    assert check_leg(leg(side="sell", qty=3), q, 9, lim) == []   # 한도를 넘은 포지션을 줄이는 주문은 통과
    assert check_leg(leg(symbol="KTB10"), q, 0, lim)             # 차단 종목
    assert check_leg(leg(symbol="ZN"), q, 0, lim)                # 허용 목록 밖
    assert check_leg(leg(type="limit", price=103.435), q, 0, lim)  # 호가 단위 위반
    assert check_leg(leg(type="limit", price=110.0), q, 0, lim)    # 현재가 대비 괴리
    assert check_leg(leg(type="limit", price=103.40), q, 0, lim) == []
    assert spec("3년")[0] == "A656C000" and num("-0000000000000003672.110") == -3672.11
    return "selfcheck 통과"


if "--selfcheck" in sys.argv:
    sys.stderr.write(selfcheck() + "\n")
    sys.exit(0)

from mcp.server.mcpserver import MCPServer  # noqa: E402  (mcp 2.x. 1.x 에서는 mcp.server.fastmcp.FastMCP)

mcp = MCPServer("nh-futures")


# ---------- 조회 도구 ----------
@mcp.tool()
def get_status() -> dict:
    """서버 상태: 접속 환경(모의/실전), 주문 한도, 정지 스위치, 오늘 보낸 주문 건수. 주문 전에 먼저 확인한다."""
    c = client("domestic")
    return {"env": c.env, "base_url": c.base, "orders_allowed_env": c.env == "paper", "halted": HALT.exists(),
            "halt_reason": HALT.read_text(encoding="utf-8") if HALT.exists() else None,
            "limits": limits(), "orders_sent_today": sent_today(), "server_time_kst": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}


@mcp.tool()
def list_symbols() -> list[dict]:
    """주문·조회할 수 있는 종목 목록(종목코드, 별칭, 국내/해외, 호가 단위, 가격 1.0 의 금액, 통화).
    다른 도구의 symbol 인자에는 종목코드와 별칭(KTB3, KTB10, ZN, ZF 등)을 모두 쓸 수 있다."""
    return [{"symbol": k, **v, "tick_value": round(v["tick"] * v["mult"], 4)} for k, v in SYMBOLS.items()]


@mcp.tool()
def get_quote(symbols: list[str]) -> list[dict]:
    """현재가·최우선 매수/매도 호가·시고저·전일 정산가·거래량. 여러 종목을 한 번에 조회한다.
    국내 국채선물은 가격 0.01 = 10,000원, 미국 국채선물 가격은 소수(1/64, 1/128 단위)로 온다."""
    return [quote(spec(s)[0]) for s in symbols]


@mcp.tool()
def get_orderbook(symbol: str) -> dict:
    """5단계 호가(가격·잔량). 체결 가능 수량과 스프레드를 확인할 때 쓴다."""
    code, v = spec(symbol)
    if v["market"] == "domestic":
        r = client("domestic").price_bid(code)
        lv = [{"ask": num(o["occurs1_ask_best_pric"]), "ask_qty": num(o["occurs1_ask_qty"]),
               "bid": num(o["occurs1_bid_best_pric"]), "bid_qty": num(o["occurs1_bid_qty"])}
              for o in r.get("Occurs1") or [] if num(o["occurs1_ask_best_pric"]) or num(o["occurs1_bid_best_pric"])]
    else:  # 국내 응답은 10행이 오지만 6~10행은 0 이라 뺀다 (2026-11-16 A656C000)
        r = client("overseas").call(O + "bid-price", {"exch_cd": nh_os.EXCH, "sym": code})
        lv = [{"ask": num(r[f"ask_pric_{i}"]), "ask_qty": num(r[f"ask_qty_{i}"]),
               "bid": num(r[f"bid_pric_{i}"]), "bid_qty": num(r[f"bid_qty_{i}"])} for i in range(1, 6)]
    return {"symbol": code, "levels": lv, "total_ask_qty": num(r.get("ask_qty")), "total_bid_qty": num(r.get("bid_qty"))}


@mcp.tool()
def get_bars(symbol: str, interval: str = "5m", count: int = 40) -> list[dict]:
    """최근 봉(시가·고가·저가·종가·거래량). interval 은 '1m','5m','15m','30m','60m' 또는 '1d'. count 는 최대 300.
    해외 분봉 시각은 한국 시간으로 보인다 [추정]. 응답 필드는 API 원본에서 occurs1_ 접두어만 뗀 것이다."""
    code, v = spec(symbol)
    count = max(1, min(int(count), 300))
    dom = v["market"] == "domestic"
    c = client(v["market"])
    if interval == "1d":
        body = ({"nght_tp": "1", "sym": code, "inq_strt_dt": "00000000", "inq_ed_dt": "99999999", "req_qty": str(count),
                 "cidx_yn": "0", "nxt_key": "99999999", "fut_cidx_exp_mod": "0"} if dom else
                {"exch_cd": nh_os.EXCH, "sym": code, "inq_strt_dt": "20000101", "inq_ed_dt": "99999999",
                 "req_qty": str(count), "cidx_yn": "0", "nxt_key": "99999999"})
        rows = c.call((D if dom else O) + "chart-daily", body).get("Occurs1") or []
    else:
        n = int(interval.rstrip("m"))
        rows = (c.chart_minute(code, dcnt=n, req_qty=count).get("Occurs1") or []) if dom else \
            c.chart_minute(code, dcnt=n, req_qty=count)
    return [{k.removeprefix("occurs1_"): (val.strip() if isinstance(val, str) else val) for k, val in r.items()}
            for r in rows[:count]]


@mcp.tool()
def get_account(market: str) -> dict:
    """예수금 요약. market 은 'domestic'(원화) 또는 'overseas'(USD). 예탁총액, 주문가능금액, 수수료, 평가손익 등."""
    today = f"{datetime.now():%Y%m%d}"
    if market == "domestic":
        d = client(market).deposit(today)
        keys = {"dps_aset_tot_amt": "예탁자산총액", "ord_psb_tot_amt": "주문가능총액", "fee": "수수료",
                "fut_cls_pl_amt": "선물청산손익", "pl_tot_pric": "총손익"}
    else:
        d = client(market).deposit("USD", today)  # biz_dt 를 비우면 400 ETR018 (11/01, 11/16 같음). 명세는 필수 아님(N)
        keys = {"dps_tot_amt": "예탁총액", "tot_acc_aset_wth_amt": "평가예탁총액", "pstn_mrgn": "포지션증거금",
                "mtn_mrgn": "유지증거금", "wdw_psb_amt": "인출가능금액", "fee": "수수료", "cls_pl_amt": "실현손익",
                "fut_opint_pl_amt": "미결제평가손익"}
    return {"market": market, "currency": "KRW" if market == "domestic" else "USD", "biz_dt": today,
            **{name: num(d.get(k)) for k, name in keys.items()}}


@mcp.tool()
def get_positions(market: str) -> dict:
    """보유 포지션. market 은 'domestic' 또는 'overseas'. 종목별 순수량(+매수/-매도), 평균가, 평가손익."""
    return {"market": market, "positions": positions(market)}


@mcp.tool()
def get_orders(market: str) -> list[dict]:
    """오늘 주문내역(체결·미체결·거부 포함). market 은 'domestic' 또는 'overseas'. 계좌번호 등은 가려서 돌려준다."""
    c = client(market)
    rows = (c.order_history().get("Occurs1") or []) if market == "domestic" else c.order_history()
    return [{k.removeprefix("occurs1_"): (v.strip() if isinstance(v, str) else v) for k, v in _nh._mask(r).items()}
            for r in rows]


# ---------- 주문 도구 ----------
@mcp.tool()
def preview_order(legs: list[dict], reason: str) -> dict:
    """주문 미리보기(1단계). 실제 주문은 보내지 않는다. 한도를 검사하고 통과하면 ticket_id 를 돌려준다.
    legs 의 각 항목: {"symbol": 종목코드 또는 별칭, "side": "buy"|"sell", "qty": 정수, "type": "market"|"limit",
    "price": 지정가일 때만}. 스프레드 주문은 legs 에 두 종목을 넣는다(예: 3년 매수 3 + 10년 매도 1).
    reason 에는 사용자가 요청한 내용과 주문 근거를 한국어로 적는다. 기록 파일에 남는다.
    결과를 사용자에게 보여 주고 동의를 받은 뒤에만 submit_order 를 호출한다."""
    lim = limits()
    problems, out = [], []
    if HALT.exists():
        problems.append(f"정지 스위치가 켜져 있음: {HALT.read_text(encoding='utf-8')}")
    if client("domestic").env != "paper":
        problems.append("모의 환경(NH_ENV=paper)이 아님")
    if not 1 <= len(legs) <= lim["max_legs"]:
        problems.append(f"legs 는 1~{lim['max_legs']}개")
    if sent_today() + len(legs) > lim["max_orders_per_day"]:
        problems.append(f"하루 주문 한도 {lim['max_orders_per_day']}건 초과 (오늘 {sent_today()}건 전송)")
    pos_cache = {}
    for leg in legs[: lim["max_legs"]]:
        try:
            code, v = spec(leg.get("symbol", ""))
        except ValueError as e:
            problems.append(str(e))
            continue
        leg = {"symbol": code, "side": leg.get("side"), "qty": leg.get("qty"), "type": leg.get("type", "market"),
               "price": leg.get("price")}
        q = quote(code)
        if v["market"] not in pos_cache:
            pos_cache[v["market"]] = positions(v["market"])
        pos = pos_cache[v["market"]].get(code, {"qty": 0})["qty"]
        bad = check_leg(leg, q, pos, lim)
        problems += [f"[{code}] {b}" for b in bad]
        if q["bid"] is None or q["ask"] is None or q["ask"] <= 0:
            problems.append(f"[{code}] 호가가 없음 (장 종료 또는 시세 없음)")
        est = leg["price"] if leg["type"] == "limit" else (q["ask"] if leg["side"] == "buy" else q["bid"])
        item = {**leg, "name": v["name"], "bid": q["bid"], "ask": q["ask"], "last": q["last"], "est_price": est,
                "position_before": pos, "currency": v["cur"]}
        if not bad and est:
            signed = leg["qty"] if leg["side"] == "buy" else -leg["qty"]
            item["position_after"] = pos + signed
            item["notional"] = round(est * v["mult"] * leg["qty"], 2)
            if code in ("A656C000", "A676C000"):
                item["est_fee_krw"] = round(item["notional"] * KTB_FEE_RATE)
            pos_cache[v["market"]].setdefault(code, {"qty": 0})["qty"] = pos + signed  # 같은 종목이 두 번 나올 때
        out.append(item)
    res = {"ok": not problems, "problems": problems, "legs": out, "reason": reason}
    if not problems:
        tid = uuid.uuid4().hex[:8]
        _tickets[tid] = {"legs": out, "reason": reason, "until": time.time() + TICKET_TTL}
        res.update(ticket_id=tid, expires_in_sec=TICKET_TTL,
                   next="사용자에게 위 내용을 보여 주고 동의를 받은 뒤 submit_order(ticket_id) 호출")
    journal("미리보기", **res)
    return res


def _send(leg):
    """주문 1건 전송 + 체결 확인. 응답이 없으면 재주문하지 않는다"""
    code, v = leg["symbol"], SYMBOLS[leg["symbol"]]
    c = client(v["market"])
    buy, mkt = leg["side"] == "buy", leg["type"] == "market"
    px = "0" if mkt else str(leg["price"])
    if v["market"] == "domestic":
        body = {"sym": code, "trd_div": "1" if buy else "2", "ord_tp_cd": "2" if mkt else "1",
                "ord_qty": str(leg["qty"]), "ord_pric": px, "exec_cnd_cd": "1"}  # 1=FAS. 시장가 FOK·FAK 는 거부 5039 (10/26 실측)
        path = D + "order"
    else:
        body = {"qt_div_cd": "1", "sym": code, "trd_div_cd": "1" if buy else "2", "glb_ord_tp_cd": "1" if mkt else "2",
                "ord_qty": str(leg["qty"]), "ord_pric": px, "stop_pric": "", "org_ord_no": "0"}
        path = O + "order"
    journal("주문 전송", leg=leg, path=path)
    try:
        res = c.call(path, body)
    except _nh.OrderUnknown as e:
        return {"symbol": code, "status": "응답 없음", "detail": str(e),
                "note": "체결됐을 수 있다. 재주문하지 말고 get_orders·get_positions 로 확인"}
    except _nh.NHError as e:
        return {"symbol": code, "status": "오류", "detail": str(e)}
    ord_no = str(res.get("ord_no", "")).strip()
    if not ord_no.lstrip("0"):
        return {"symbol": code, "status": "거부", "detail": f"{res.get('msg_cd') or res.get('err_cd')} "
                                                          f"{res.get('msg_cntn') or res.get('err_msg')}"}
    fill = c.find_fill(ord_no, tries=30 if mkt else 5)
    if fill is None:
        return {"symbol": code, "status": "접수(체결 미확인)", "ord_no": ord_no,
                "note": "지정가면 미체결일 수 있다. get_orders 로 확인, 필요하면 cancel_order"}
    if fill["reject"]:
        return {"symbol": code, "status": "거부", "ord_no": ord_no, "detail": fill["reject"]}
    return {"symbol": code, "status": "체결" if fill["qty"] >= leg["qty"] else "부분 체결", "ord_no": ord_no,
            "filled_qty": fill["qty"], "fill_price": fill["px"], "fill_time": fill["time"]}


@mcp.tool()
def submit_order(ticket_id: str) -> dict:
    """주문 전송(2단계). preview_order 가 준 ticket_id 로만 보낼 수 있고, 사용자가 미리보기 내용에 동의한 뒤에만 호출한다.
    legs 를 순서대로 시장가/지정가로 보내고 체결을 확인한다. 한 건이라도 체결되지 않으면 남은 legs 는 보내지 않고 멈춘다
    (이미 체결된 leg 는 되돌리지 않는다. 결과를 사용자에게 알리고 어떻게 할지 묻는다)."""
    t = _tickets.pop(ticket_id, None)  # 1회용
    if t is None:
        return {"ok": False, "error": "없는 ticket_id (이미 썼거나 서버가 재시작됨). preview_order 부터 다시"}
    if time.time() > t["until"]:
        return {"ok": False, "error": f"주문표 만료({TICKET_TTL}초). 시세가 바뀌었을 수 있으니 preview_order 부터 다시"}
    if HALT.exists():
        return {"ok": False, "error": f"정지 스위치가 켜져 있음: {HALT.read_text(encoding='utf-8')}"}
    if sent_today() + len(t["legs"]) > limits()["max_orders_per_day"]:
        return {"ok": False, "error": "하루 주문 한도 초과"}
    results, stopped = [], False
    for leg in t["legs"]:
        r = _send(leg)
        results.append(r)
        journal("주문 결과", ticket_id=ticket_id, leg=leg, result=r)
        if r["status"] != "체결":
            stopped = True
            break
    markets = {SYMBOLS[leg["symbol"]]["market"] for leg in t["legs"]}
    res = {"ok": not stopped, "results": results, "unsent_legs": t["legs"][len(results):],
           "positions_after": {m: positions(m) for m in markets}, "reason": t["reason"]}
    journal("주문 종료", ticket_id=ticket_id, **res)
    return res


@mcp.tool()
def preview_close(symbol: str, reason: str) -> dict:
    """보유 포지션 전량을 시장가로 청산하는 주문 미리보기. 포지션이 한도보다 크면 주문당 한도만큼만 줄인다.
    돌려준 ticket_id 를 사용자 동의 후 submit_order 에 넘긴다."""
    code, v = spec(symbol)
    pos = positions(v["market"]).get(code, {"qty": 0})["qty"]
    if pos == 0:
        return {"ok": False, "problems": [f"{code} 보유 포지션 없음"]}
    qty = min(abs(pos), limits()["max_qty_per_order"])
    return preview_order([{"symbol": code, "side": "sell" if pos > 0 else "buy", "qty": qty, "type": "market"}], reason)


@mcp.tool()
def cancel_order(symbol: str, side: str, qty: int, order_no: str) -> dict:
    """미체결 주문 취소. side 는 원주문의 buy|sell, qty 는 취소할 수량(미체결 잔량 이하), order_no 는 원주문번호.
    get_orders 로 미체결 잔량을 확인한 뒤 호출한다."""
    code, v = spec(symbol)
    c = client(v["market"])
    if v["market"] == "domestic":
        path, body = D + "cancel", {"sym": code, "trd_div": "1" if side == "buy" else "2", "ord_qty": str(qty),
                                    "org_ord_no": str(order_no)}
    else:  # 해외는 주문 경로 하나로 신규·정정·취소를 구분한다 (qt_div_cd 3=취소, 명세 overseas/order)
        path, body = O + "order", {"qt_div_cd": "3", "sym": code, "trd_div_cd": "1" if side == "buy" else "2",
                                   "glb_ord_tp_cd": "2", "ord_qty": str(qty), "ord_pric": "0", "stop_pric": "",
                                   "org_ord_no": str(order_no)}
    journal("취소 전송", symbol=code, side=side, qty=qty, org_ord_no=order_no)
    try:
        res = c.call(path, body)
    except _nh.NHError as e:
        res = {"error": str(e)}
    journal("취소 결과", symbol=code, org_ord_no=order_no, result=res)
    return _nh._mask(res)


@mcp.tool()
def halt_trading(reason: str) -> dict:
    """정지 스위치를 켠다. 이후 preview_order·submit_order 가 전부 거부된다(조회와 취소는 가능).
    이상 징후(연속 거부, 예상과 다른 잔고, 사용자의 중단 요청)가 있으면 호출한다.
    해제는 사람이 final/results/HALT 파일을 지워야 한다. 도구로는 해제할 수 없다."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    HALT.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S} {reason}", encoding="utf-8")
    journal("정지", reason=reason)
    return {"halted": True, "reason": reason, "how_to_resume": f"사람이 {HALT} 파일을 삭제"}


if __name__ == "__main__":
    mcp.run()
