# 6주차 실전: 2주차 볼린저 평균회귀 + 위험관리 (risk.py). 모의계좌 코스닥150 선물 A066C000, 2계약 분할 청산
#   python trade06.py          주문 (작업 스케줄러는 run_trade06.bat 이 실행)
#   python trade06.py --dry    주문 없이 판정만 (지금 시세를 체결가로 본다)
# 흐름: 10초마다 현재가 → 손절 판정 / 1분마다 이상 점검, 5분봉 마감마다 진입과 중심선, 반대 밴드 청산 / 15:25 전량 청산
# 이상 감지(잔고 불일치, 주문 실패 반복, 시세 조회 실패 지속)면 알림 → 보유 청산 → 그날 신규 진입 중지
# 주문 전에 미체결과 브로커 잔고를 확인한다. 다르면 주문하지 않는다 (중복 주문 방지)
# 재실행하면 results/state06.json 과 브로커 잔고, 오늘 기록을 읽어 이어 관리한다 (watchdog06.py 가 재실행)
# 수동 정지: week06 폴더에 STOP 파일을 만들면 보유를 청산하고 종료
import ctypes
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import risk as R
from alert import alert
from data06 import RESULTS, _nh

sys.path.append(str(Path(__file__).resolve().parent.parent / "week02"))
from fetch_bars import parse  # noqa: E402

from backtest06 import ENTRY_FROM, ENTRY_UNTIL, signals  # noqa: E402

HERE = Path(__file__).resolve().parent
DRY = "--dry" in sys.argv
LIVE = R.Rules(stop_touch=True, limit="worst", lots=2, split=True)  # 11/22 세진 결정
TODAY = f"{datetime.now():%Y%m%d}"
JOURNAL = RESULTS / f"journal_{TODAY}{'_dry' if DRY else ''}.jsonl"
STATE = RESULTS / ("state06_dry.json" if DRY else "state06.json")
HEARTBEAT = RESULTS / "heartbeat.json"
STOP_FILE = HERE / "STOP"
OPEN_AT, GIVE_UP_AT = "09:00", "15:34"    # 모의 국내 운영 09:00~, 15:35 종료 단일가 전까지 청산 재시도
LAST_AT = "15:40"                         # 오류가 이어져도 이 시각에는 끝낸다
POLL = 10                                 # 손절 판정 간격(초). 2주차는 60초라 손절 6회 중 5회가 손절선을 2~24틱 넘겨 체결
PRICE_FAIL_ALERT, PRICE_FAIL_HALT = 6, 18  # 시세 조회 연속 실패: 1분이면 알림, 3분이면 이상으로 보고 정리
ORDER_FAIL_HALT = 2                       # 그날 주문 실패(거부, 응답 없음, 미체결) 2회면 이상
SETTLE_TRIES = 10                         # 체결 뒤 잔고 반영 확인 (1초 간격)
FEE_RATE = 2393 / ((1221.0 + 1220.3) * R.MULT)  # 2주차 10/26 실측 수수료율 (손익 추정용)


def journal(event, **kw):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **kw}
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(_nh._mask(rec), ensure_ascii=False, default=str) + "\n")
    if event not in ("tick", "price"):
        print(json.dumps(rec, ensure_ascii=False, default=str)[:300], flush=True)


def write_atomic(path, obj):
    """읽는 쪽(감시)이 반쯤 쓰인 파일을 보지 않게 임시 파일에 쓰고 바꿔치기한다"""
    tmp = path.with_suffix(".tmp")
    for _ in range(20):
        try:
            tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
    return False


def single_instance():
    """bat 재실행과 감시 재실행이 겹쳐도 하나만 돈다. 프로세스가 죽으면 윈도우가 잠금을 푼다"""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k.CreateMutexW(None, False, "NH_trade06_dry" if DRY else "NH_trade06")
    return None if ctypes.get_last_error() == 183 else handle  # ERROR_ALREADY_EXISTS


# ------------------------------------------------------------------ 판정 (순수 함수, selfcheck 로 확인)
def flat():
    return {"day": TODAY, "side": 0, "lots": 0, "stage": 0, "entry_px": None, "entry_t": None, "trade": None,
            "halt": None, "pending": None}


def on_price(st, px, rules):
    """10초마다. 손절(또는 분할 청산 뒤 본전) 판정"""
    if st["side"] and (rules.stop or st["stage"]) and R.stop_hit(st["side"], st["entry_px"], st["stage"], px):
        return "exit", st["lots"], "손절" if st["stage"] == 0 else "본전"
    return None


def on_bar(st, hm, row, pnl, rules):
    """1분마다. row 는 5분봉 마감 분에만 들어온다 (아니면 None)"""
    if st["side"]:
        if hm >= R.EXIT_AT:
            return "exit", st["lots"], "15:25"
        if row is None:
            return None
        if st["stage"] == 0 and row["exit_long" if st["side"] > 0 else "exit_short"]:
            part = rules.split and st["lots"] > 1
            return "exit", st["lots"] // 2 if part else st["lots"], "중심선"
        if st["stage"] == 1 and row["far_long" if st["side"] > 0 else "far_short"]:
            return "exit", st["lots"], "반대 밴드"
        return None
    if st["halt"] or row is None or not row["entry"] or not (ENTRY_FROM <= hm < ENTRY_UNTIL):
        return None
    if not R.entry_allowed(rules, pnl):
        return "skip", int(row["entry"]), "일일 한도(다음 손절 포함)"
    return "enter", int(row["entry"]), rules.lots


# ------------------------------------------------------------------ 실행
class Trader:
    def __init__(self):
        self.nh = _nh.NH()
        if self.nh.env != "paper":
            sys.exit("NH_ENV=paper 에서만 실행한다")
        self.st = flat()
        self.pnl = 0
        self.order_fails = self.price_fails = self.errors = 0
        self.last_px = self.last_min = self.exit_min = None
        self.alarm = None  # 주문 도중 발견한 이상. 다음 판정(10초 안)에서 처리한다
        call = self.nh.call

        def call_and_beat(path, body):  # 체결 대기(최대 60초) 중에도 heartbeat 가 끊기지 않게
            self.beat()
            return call(path, body)
        self.nh.call = call_and_beat

    # --- 기록
    def save(self):
        if not write_atomic(STATE, self.st):
            journal("state_write_fail", state=self.st)

    def beat(self, ended=False):
        """watchdog06.py 가 이 파일의 시각으로 프로그램이 살아 있는지 본다. ended 면 다시 띄우지 않는다"""
        if DRY:
            return
        now = datetime.now()
        write_atomic(HEARTBEAT, {"ts": now.isoformat(timespec="seconds"), "pid": os.getpid(), "day": TODAY,
                                 "hm": f"{now:%H:%M}", "side": self.st["side"], "lots": self.st["lots"],
                                 "pending": self.st["pending"], "ended": ended})

    def clear(self):
        self.st.update(day=TODAY, side=0, lots=0, stage=0, entry_px=None, entry_t=None, trade=None)
        self.save()

    def expected(self):
        return self.st["side"] * self.st["lots"]

    def restore(self):
        saved, existed = flat(), STATE.exists()
        if existed:
            saved.update(json.loads(STATE.read_text(encoding="utf-8")))
        recs = []
        for line in JOURNAL.read_text(encoding="utf-8").splitlines() if JOURNAL.exists() else []:
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass  # 강제 종료로 잘린 줄
        self.pnl = sum(r["pnl"] for r in recs if r["event"] == "exit")
        self.order_fails = sum(r["event"] == "order_fail" for r in recs)
        today = existed and saved["day"] == TODAY
        if today or saved["side"]:
            self.st = saved
        self.beat()
        pos = self.expected() if DRY else self.nh.position()[0]
        journal("start", dry=DRY, rules=LIVE.__dict__, broker=pos, state=saved, pnl_today=self.pnl, pid=os.getpid())
        if pos != self.expected():
            if today:  # 주문과 기록 사이에 죽은 경우. 방치하지 않고 이상으로 정리한다
                self.alarm = f"재시작 시 잔고 {pos} ≠ 기록 {self.expected()}"
            else:      # 이 프로그램이 만든 보유인지 알 수 없다
                alert(f"시작 시 잔고 {pos} ≠ 기록 {self.expected()}. 주문하지 않고 종료 (직접 확인 필요)", journal)
                self.beat(ended=True)
                sys.exit(2)
        self.save()

    def price(self):
        """현재가. 실패하면 None (지난 가격으로 손절을 판정하지 않는다)"""
        try:
            self.last_px, self.price_fails = float(self.nh.price()["last_pric"]), 0
            return self.last_px
        except Exception as e:  # noqa: BLE001
            self.price_fails += 1
            journal("price_fail", n=self.price_fails, err=repr(e))
            if self.price_fails == PRICE_FAIL_ALERT:
                alert(f"시세 조회 {self.price_fails}회 연속 실패 (보유 {self.expected()})", journal)
            if self.price_fails >= PRICE_FAIL_HALT and self.st["side"] and not self.st["halt"]:
                self.alarm = "시세 조회 3분 연속 실패"
        return None

    # --- 주문
    def open_qty(self, ord_no):
        key = str(ord_no).strip().lstrip("0")
        for r in self.nh.order_history().get("Occurs1") or []:
            if r.get("occurs1_ord_no", "").strip().lstrip("0") == key:
                if (r.get("occurs1_ord_rejt_rsn") or "").strip():
                    return 0
                return int(float(r.get("occurs1_rem_ord_qty") or 0))
        return 0

    def send(self, side, qty, why):
        """시장가 → 체결 확인 → 잔고 확인. 반환: (주문 뒤 잔고, 체결가, 평균가). 주문하지 않았으면 잔고는 None
        중복 주문 방지: 앞 주문이 미체결이거나 브로커 잔고가 기록과 다르면 주문하지 않는다"""
        want = self.expected() + side * qty
        if DRY:
            journal("order_dry", why=why, side=side, qty=qty, px=self.last_px)
            return want, self.last_px, self.last_px
        if self.st["pending"]:
            if self.open_qty(self.st["pending"]):
                journal("order_wait", why=why, pending=self.st["pending"])
                return None, None, None
            self.st["pending"] = None
            self.save()
        before = self.nh.position()[0]
        if before != self.expected():
            self.alarm = f"주문 전 잔고 {before} ≠ 기록 {self.expected()}"
            return None, None, None
        ord_no = fill = pos = avg = None
        try:
            ord_no = self.nh.order(side, qty)["ord_no"].strip()
            fill = self.nh.find_fill(ord_no, tries=60)  # 4주차 11/12: 접수까지 30초 걸린 주문이 있었다
            journal("order", why=why, side=side, qty=qty, ord_no=ord_no, fill=fill)
        except _nh.OrderUnknown as e:
            journal("order_unknown", why=why, side=side, qty=qty, err=str(e))
        except Exception as e:  # noqa: BLE001  거부, 조회 실패. 결과는 아래 잔고로 판단한다
            journal("order_error", why=why, side=side, qty=qty, ord_no=ord_no, err=repr(e))
        for _ in range(SETTLE_TRIES):
            try:
                pos, avg = self.nh.position()
                if pos == want:
                    return pos, (fill or {}).get("px"), avg
            except Exception as e:  # noqa: BLE001
                journal("position_fail", err=repr(e))
            time.sleep(1)
        try:
            if ord_no and self.open_qty(ord_no):
                self.st["pending"] = ord_no
                self.save()
        except Exception as e:  # noqa: BLE001
            journal("open_qty_fail", ord_no=ord_no, err=repr(e))
        self.order_fails += 1
        journal("order_fail", why=why, before=before, after=pos, want=want, n=self.order_fails)
        if self.order_fails >= ORDER_FAIL_HALT and not self.st["halt"]:
            self.alarm = f"주문 실패 {self.order_fails}회 ({why})"
        return pos, None, avg

    def enter(self, side, lots):
        pos, px, avg = self.send(side, lots, "진입")
        if pos == side * lots:
            now, px = datetime.now(), px or avg or self.last_px
            self.st.update(day=TODAY, side=side, lots=lots, stage=0, entry_px=px, entry_t=f"{now:%H:%M:%S}",
                           trade=f"{now:%m%d %H:%M}")
            self.save()
            journal("enter", side=side, lots=lots, px=px, stop=R.stop_price(side, px, 0))
        elif pos:
            self.alarm = f"진입 뒤 잔고 {pos} (원한 값 {side * lots})"

    def exit(self, n, why):
        side, e_px, left = self.st["side"], self.st["entry_px"], self.st["lots"] - n
        pos, px, _ = self.send(-side, n, why)
        if pos is None or pos != side * left:
            journal("exit_failed", reason=why, pos=pos)  # 다음 판정에서 다시 시도
            return False
        x = px or self.last_px or e_px
        gain = round(side * (x - e_px) * R.MULT * n - (x + e_px) * FEE_RATE * R.MULT * n)
        self.pnl += gain
        journal("exit", reason=why, trade=self.st["trade"], side=side, lots=n, entry=e_px, exit=x, pnl=gain,
                pnl_today=self.pnl, left=left)
        if left:
            self.st.update(lots=left, stage=1)
            self.save()
            journal("stop_moved", trade=self.st["trade"], stop=R.stop_price(side, e_px, 1))
        else:
            self.clear()
        return True

    def halt(self, why):
        """이상 감지: 알림 → 브로커 잔고 기준으로 청산 → 그날 신규 진입 중지"""
        if self.st["halt"] != why:
            self.st["halt"] = why
            self.save()
            alert(f"이상 감지: {why}. 보유 청산 후 오늘 신규 진입 중지", journal)
        pos, avg = (self.expected(), self.st["entry_px"]) if DRY else self.nh.position()
        if not pos:
            self.clear()
            return
        side = 1 if pos > 0 else -1
        if side != self.st["side"] or self.st["entry_px"] is None:
            self.st["entry_px"] = avg or self.last_px
        self.st.update(side=side, lots=abs(pos))
        self.save()
        self.exit(abs(pos), "이상 정리")

    # --- 1분 점검
    def check_broker(self):
        if DRY:
            return
        try:
            pos = self.nh.position()[0]
        except Exception as e:  # noqa: BLE001
            journal("position_fail", err=repr(e))
            return
        if pos != self.expected():
            self.halt(f"잔고 불일치 (브로커 {pos}, 기록 {self.expected()})")
        elif pos and self.st["halt"]:
            self.halt(self.st["halt"])  # 정리가 끝날 때까지 매분 재시도

    def row(self, boundary):
        try:
            b5 = parse(self.nh.chart_minute(dcnt=5, req_qty=60)["Occurs1"], 5)
            sig = signals(b5[b5.close_t <= boundary])
        except Exception as e:  # noqa: BLE001
            journal("chart_fail", err=repr(e))
            return None
        if boundary not in sig.index:
            journal("bar_lag", hm=f"{boundary:%H:%M}")
            return None
        return sig.loc[boundary]

    # --- 루프
    def step(self, now):
        """10초마다 한 번. True 면 정상 종료"""
        hm = now.strftime("%H:%M")
        if self.alarm:
            why, self.alarm = self.alarm, None
            try:
                self.halt(why)
            except Exception:
                self.alarm = why
                raise
        px = self.price()
        if self.st["side"] and self.st["day"] != TODAY:
            if not self.exit(self.st["lots"], "전일 보유 정리"):
                return False
        if STOP_FILE.exists():
            if self.st["side"]:
                self.exit(self.st["lots"], "STOP 파일")
                return False
            journal("end", why="STOP 파일", pnl_today=self.pnl)
            return True
        boundary = now.replace(second=0, microsecond=0)
        act = on_price(self.st, px, LIVE) if px is not None else None
        if act:
            self.exit(act[1], act[2])
            self.exit_min = boundary  # 방금 청산한 분에는 진입하지 않는다 (백테스트와 같음)
        if boundary != self.last_min and now.second >= 5:  # 봉 확정을 5초 기다린다 (2주차와 같음)
            self.last_min = boundary
            self.check_broker()
            row = self.row(boundary) if boundary.minute % 5 == 0 else None
            journal("tick", hm=hm, px=px, side=self.st["side"], lots=self.st["lots"], stage=self.st["stage"],
                    entry=self.st["entry_px"], pnl_today=self.pnl, sig=None if row is None else int(row["entry"]))
            act = None if self.exit_min == boundary or self.alarm else on_bar(self.st, hm, row, self.pnl, LIVE)
            if act and act[0] == "exit":
                self.exit(act[1], act[2])
            elif act and act[0] == "enter":
                self.enter(act[1], act[2])
            elif act:
                journal("skip", side=act[1], why=act[2], pnl_today=self.pnl)
            if hm >= R.EXIT_AT and not self.st["side"] and not self.alarm:
                journal("end", why="15:25", pnl_today=self.pnl, halt=self.st["halt"])
                return True
        return False

    def run(self):
        self.restore()
        while True:
            now = datetime.now()
            hm = now.strftime("%H:%M")
            self.beat()
            if (hm >= GIVE_UP_AT and self.st["side"]) or hm >= LAST_AT:
                left = bool(self.st["side"] or self.alarm)
                if left:
                    alert(f"{hm}까지 청산 실패, 보유 {self.expected()}. 직접 확인 필요", journal)
                self.beat(ended=True)
                sys.exit(2 if left else 0)
            if hm >= OPEN_AT:
                try:
                    if self.step(now):
                        self.beat(ended=True)
                        return
                    self.errors = 0
                except Exception as e:  # noqa: BLE001  한 번의 실패로 손절 감시를 멈추지 않는다
                    self.errors += 1
                    journal("error", hm=hm, n=self.errors, err=repr(e))
                    if self.errors == PRICE_FAIL_ALERT:
                        alert(f"판정 오류 {self.errors}회 연속: {e!r}", journal)
            time.sleep(POLL - time.time() % POLL)


def selfcheck():
    r = LIVE
    st = flat()
    row = {"entry": 1, "exit_long": False, "exit_short": False, "far_long": False, "far_short": False}
    assert on_bar(st, "10:30", row, 0, r) == ("enter", 1, r.lots)
    assert on_bar(st, "10:30", None, 0, r) is None                      # 5분봉 마감이 아닌 분
    assert on_bar(st, "15:25", row, 0, r) is None                       # 진입 시간 뒤
    assert on_bar(st, "10:30", row, -81_400 * r.lots, r)[0] == "skip"   # 손절 1회 뒤 다음 손절이 한도를 넘음
    assert on_bar({**st, "halt": "x"}, "10:30", row, 0, r) is None      # 이상 감지 뒤 진입 중지
    s = R.STOP_TICKS * R.TICK
    long2 = {**st, "side": 1, "lots": 2, "entry_px": 1000.0}
    assert on_price(long2, 1000 - s + R.TICK, r) is None
    assert on_price(long2, 1000 - s, r) == ("exit", 2, "손절")
    assert on_bar(long2, "11:00", {**row, "exit_long": True}, 0, r) == ("exit", 1, "중심선")
    assert on_bar({**long2, "lots": 1}, "11:00", {**row, "exit_long": True}, 0, r) == ("exit", 1, "중심선")
    half = {**long2, "lots": 1, "stage": 1}
    assert on_price(half, 1000.1, r) is None and on_price(half, 1000.0, r) == ("exit", 1, "본전")
    assert on_bar(half, "11:05", {**row, "exit_long": True}, 0, r) is None       # 남은 1계약은 중심선에서 청산하지 않음
    assert on_bar(half, "11:05", {**row, "far_long": True}, 0, r) == ("exit", 1, "반대 밴드")
    assert on_bar(half, "15:25", None, 0, r) == ("exit", 1, "15:25")
    short2 = {**st, "side": -1, "lots": 2, "entry_px": 1000.0}
    assert on_price(short2, 1000 + s, r) == ("exit", 2, "손절")


if __name__ == "__main__":
    selfcheck()
    if "--check" in sys.argv:
        print("selfcheck 통과")
    else:
        lock = single_instance()
        if not lock:
            print("이미 실행 중. 종료", flush=True)
            sys.exit(0)
        Trader().run()
