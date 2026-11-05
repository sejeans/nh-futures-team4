# NH선물 해외선물 REST 클라이언트 — 2주차 nh.py 의 토큰·호출 간격·재시도·로그·실주문 차단을 그대로 쓰고 해외 경로만 붙인다
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "week02"))
import nh as _nh  # noqa: E402

_nh.LOG_DIR = HERE / "results" / "api_log"
_nh.MASK_SUFFIX = ("ac_no", "ac_nm", "ip_addr")  # 해외 주문내역에는 occurs1_ip_addr 가 있다 (명세 overseas/order-history)
NHError, OrderUnknown = _nh.NHError, _nh.OrderUnknown

EXCH = "FCME"  # F(선물) + 거래소코드 (명세 overseas/price)
ZN, ZF = "ZNZ26", "ZFZ26"  # 미국 10년·5년 국채 2026년 12월물
# product-detail 응답 (results/specs_FG1_20261101.json, 2026-11-01 조회): 틱 크기·틱 가치(USD)
SPEC = {"ZN": {"tick": 0.015625, "tick_usd": 15.625}, "ZF": {"tick": 0.0078125, "tick_usd": 7.8125}}
P = "/trade/v1/overseas/"


class NHOverseas(_nh.NH):
    def pages(self, name, body, start="", max_pages=100):
        """nxt_key 를 따라가며 Occurs1 을 모은다. 키가 비거나 9 로만 채워지면 끝.
        chart-minute 은 마지막 페이지에 9 32자리를 주고, 그 키로 다시 부르면 처음 페이지로 돌아간다 (2026-11-01 로그)"""
        out, key = [], start
        for _ in range(max_pages):
            r = self.call(P + name, {**body, "nxt_key": key})
            out += r.get("Occurs1") or []
            nxt = (r.get("nxt_key") or "").strip()
            if not r.get("Occurs1") or set(nxt) <= {"9"} or nxt == key:
                return out
            key = nxt
        raise NHError(f"{name}: {max_pages}페이지를 넘었다 (nxt_key 반복 의심)")

    # --- 시세 ---
    def price(self, sym=ZN):
        # 한 번에 한 종목만. Iccurs1 에 2종목을 넣으면 빈 응답이 온다 (2026-11-01, 오류 제보 후보)
        return self.call(P + "price", {"Iccurs1": [{"iccurs1_exch_cd": EXCH, "iccurs1_sym": sym}]})["Occurs1"][0]

    def chart_minute(self, sym=ZN, dcnt=5, req_qty=300, start="00000000", end="99999999", all_pages=False,
                     max_pages=100):
        # req_qty 를 9999 로 줘도 한 페이지에 495봉까지만 온다 (2026-11-01)
        body = {"exch_cd": EXCH, "sym": sym, "inq_strt_dt": start, "strt_tm": "000000", "inq_ed_dt": end,
                "ed_tm": "235959", "req_qty": str(req_qty), "dcnt": str(dcnt), "cidx_yn": "0"}
        if all_pages:
            return self.pages("chart-minute", body, start="99999999", max_pages=max_pages)
        return self.call(P + "chart-minute", {**body, "nxt_key": "99999999"}).get("Occurs1") or []

    def chart_daily(self, sym=ZN, start="20000101", end="99999999", cidx="0"):
        # 만기된 월물(ZNU26 등)은 3회 재시도 후 실패 (2026-11-05). 상장일부터 오늘(진행 중인 봉)까지 온다
        return self.pages("chart-daily", {"exch_cd": EXCH, "sym": sym, "inq_strt_dt": start, "inq_ed_dt": end,
                                          "req_qty": "9999", "cidx_yn": cidx}, start="99999999")

    def product_detail(self, grp="FG1"):  # FG1 = 금리
        return self.pages("product-detail", {"fut_opt_div_cd": "F", "prd_grp_cd": grp, "exch_cd": "", "cur_cd": "",
                                             "sett_cd": "", "prd_cd": "", "prd_nm": ""})

    def market_operations(self, grp="FG1"):
        return self.pages("market-operations", {"fut_opt_div_cd": "F", "prd_grp_cd": grp, "exch_cd": "",
                                                "cur_cd": "", "prd_cd": "", "prd_nm": ""})

    # --- 계좌 ---
    def deposit(self, cur="USD", biz_dt=""):
        return self.call(P + "deposit", {"biz_dt": biz_dt, "cur_cd": cur, "cvs_div": "1"})

    def open_interest(self):
        return self.pages("open-interest", {})

    def order_history(self):
        return self.pages("order-history", {"inq_div": "0", "prd_cd": "", "trd_div_cd": "0"})

    def cumulative_pl(self, start, end):
        """기간 누적 실현손익·수수료. 마지막 행이 환산 합계 (명세 overseas/cumulative-pl)"""
        return self.pages("cumulative-pl", {"inq_strt_dt": start, "inq_ed_dt": end, "prd_cd": "",
                                            "cvs_cur_cd": "USD", "cur_cd": ""})

    def position(self, sym=ZN):
        """잔고 기준 순포지션(+매수/-매도 계약 수)과 평균가. 잔고 trd_tp 1=매수 2=매도 (명세)"""
        rows = [r for r in self.open_interest() if r.get("occurs1_sym", "").strip() == sym]
        pos = sum({"1": 1, "2": -1}[r["occurs1_trd_tp"].strip()] * int(float(r["occurs1_opint_qty"])) for r in rows)
        return pos, (float(rows[0]["occurs1_avg_pric"]) if rows else None)

    def find_fill(self, ord_no, tries=5):
        """주문내역에서 체결(또는 거부)을 찾는다. 못 찾으면 None. 주문상태 6=전체체결 9=거부 (명세)"""
        key = str(ord_no).strip().lstrip("0")
        for _ in range(tries):
            for r in self.order_history():
                if r.get("occurs1_ord_no", "").strip().lstrip("0") != key:
                    continue
                qty = float(r.get("occurs1_exec_qty") or 0)
                reject = (r.get("occurs1_rejt_rsn") or "").strip()
                if qty > 0 or reject or r.get("occurs1_ord_sts", "").strip() == "9":
                    px = float(r.get("occurs1_ord_avg_pric") or 0) or float(r.get("occurs1_exec_pric") or 0)
                    return {"qty": qty, "px": px or None, "status": r.get("occurs1_ord_sts"),
                            "time": r.get("occurs1_exec_tm"), "reject": reject or r.get("occurs1_err_msg", "").strip()}
            time.sleep(1)
        return None

    # --- 주문 ---
    def order(self, side, qty=1, sym=ZN):
        """시장가 신규주문. side +1 매수 / -1 매도. 해외 주문에는 국내의 체결조건(exec_cnd_cd) 필드가 없다"""
        res = self.call(P + "order", {"qt_div_cd": "1", "sym": sym, "trd_div_cd": "1" if side > 0 else "2",
                                      "glb_ord_tp_cd": "1", "ord_qty": str(qty), "ord_pric": "0", "stop_pric": "",
                                      "org_ord_no": "0"})
        if not str(res.get("ord_no", "")).strip().lstrip("0"):
            raise NHError(f"주문 거부 {res.get('err_cd')} {res.get('err_msg')}")
        return res


if __name__ == "__main__":
    # 조회만 한다. 주문은 보내지 않는다
    nh = NHOverseas()
    print("환경:", nh.env, nh.base)
    for s in (ZN, ZF):
        p = nh.price(s)
        print(s, p["occurs1_sym_nm"], "현재가", float(p["occurs1_last_pric"]), "영업일", p["occurs1_biz_dt"],
              "거래시간", p["occurs1_trd_tm"])
    d = nh.deposit()
    print("deposit USD: 예탁총액", d.get("dps_tot_amt"), "/ 주문가능", d.get("ord_psb_amt"), "/ 기준환율", d.get("ref_exrt"))
    print("open_interest:", len(nh.open_interest()), "건 / order_history:", len(nh.order_history()), "건")
