# 모의계좌 당일 체결내역, 잔고, 예수금을 조회해 표로 출력한다 (screenshots/ 캡처용). 주문은 내지 않는다
#   python show_account.py     장 마감(15:30 청산) 뒤 실행하고 터미널 화면을 캡처
# 당일 주문내역 API는 지난 날짜를 조회할 수 없으므로 그날 안에 실행해야 한다
# 원본 응답은 results/account_YYYYMMDD_HHMMSS.json 에 남긴다 (계좌번호 등은 마스킹)
import json
import time
from datetime import datetime

from fetch_data import RESULTS, _nh

SIDE = {"1": "매수", "2": "매도"}


def w(s, n, right=False):
    """한글을 2칸으로 계산해 n칸에 맞춘다 (터미널 캡처용 정렬)"""
    s = str(s)
    gap = " " * max(0, n - len(s) - sum(1 for c in s if ord(c) >= 0x1100))
    return gap + s if right else s + gap


def num(s):
    return float(s or 0)


def tm(s):  # "153001783" -> "15:30:01.783"
    s = (s or "").strip()
    return f"{s[:2]}:{s[2:4]}:{s[4:6]}.{s[6:9]}" if len(s) >= 6 else s


def safe(f, tries=3):
    """11/18 09:00:03 order-history가 400 EGW009(계좌번호가 잘못되었습니다)를 한 번 냈고, 16:50 재조회는 정상이었다.
    일시 오류로 보고 10초 간격으로 다시 묻는다. 끝내 실패하면 빈 응답으로 두고 나머지 표는 계속 찍는다"""
    for i in range(tries):
        try:
            return f()
        except _nh.NHError as e:
            print(f"[{f.__name__} 실패 {i + 1}/{tries}] {e}")
            if i + 1 < tries:
                time.sleep(10)
    return {}


def main():
    nh = _nh.NH()
    now = datetime.now()
    hist, bal, dep = (safe(f) for f in (nh.order_history, nh.open_interest, nh.deposit))

    print(f"NH선물 모의계좌 조회  {now:%Y-%m-%d %H:%M:%S}  (team-04, week05/show_account.py)")
    print()
    rows = sorted(hist.get("Occurs1") or [], key=lambda r: r.get("occurs1_ord_no", ""))
    print(f"[당일 주문, 체결내역]  {len(rows)}건")
    print(" ".join([w("거래일", 8), w("주문번호", 8, 1), w("종목", 8), w("구분", 4), w("유형", 6), w("주문", 4, 1),
                    w("체결", 4, 1), w("체결가", 8, 1), w("체결시각", 12), "상태"]))
    for r in rows:
        print(" ".join([w(r["occurs1_trd_dt"], 8), w(r["occurs1_ord_no"].lstrip("0"), 8, 1), w(r["occurs1_sym"].strip(), 8),
                        w(SIDE.get(r["occurs1_trd_div"].strip(), "?"), 4), w(r["occurs1_pric_cnd_nm"].strip(), 6),
                        w(f"{num(r['occurs1_ord_qty']):.0f}", 4, 1), w(f"{num(r['occurs1_exec_qty']):.0f}", 4, 1),
                        w(f"{num(r['occurs1_exec_pric']):.2f}", 8, 1), w(tm(r["occurs1_exch_exec_tm"]), 12),
                        r["occurs1_ord_sts_nm"].strip(), r["occurs1_ord_rejt_rsn"].strip()]))
    print()
    pos = bal.get("Occurs1") or []
    print(f"[잔고]  {len(pos)}종목")
    for p in pos:
        print(f"  {p['occurs1_sym'].strip()} {p['occurs1_trd_div_nm_v2'].strip()} {num(p['occurs1_opint_qty']):.0f}계약 "
              f"평균가 {num(p['occurs1_avg_pric']):.2f} 현재가 {num(p['occurs1_close_pric']):.2f} 평가손익 {num(p['occurs1_pl_amt']):,.0f}원")
    if not pos:
        print("  보유 없음")
    print()
    print("[예수금]  0이 아닌 항목")
    for k, v in dep.items():
        if k in ("nxt_key", "nrec") or isinstance(v, (list, dict)):
            continue
        try:
            if num(v):
                print(f"  {k}: {num(v):,.0f}")
        except ValueError:
            pass

    out = RESULTS / f"account_{now:%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(_nh._mask({"t": now.isoformat(timespec="seconds"), "order_history": hist,
                                        "open_interest": bal, "deposit": dep}), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print()
    print(f"원본 응답: results/{out.name}")


if __name__ == "__main__":
    main()
