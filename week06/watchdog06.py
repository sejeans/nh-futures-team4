# 감시 프로그램: 작업 스케줄러가 평일 장중 2분마다 실행한다. 주문은 내지 않는다
#   1) trade06.py 의 heartbeat.json 이 90초 넘게 갱신되지 않으면 알림 → (멈춘 프로세스가 있으면 종료) → run_trade06.bat 재실행
#      trade06.py 는 시작할 때 브로커 잔고와 state06.json 을 읽어 보유를 이어 관리한다
#   2) 15:36 이후 보유가 남아 있으면 미청산 알림 (5주차 11/20 사고: 14:02에 실행 창이 닫혀 손절, 청산이 실행되지 않음)
# 모든 점검 결과를 results/watchdog_YYYYMMDD.jsonl 에 남긴다
#   python watchdog06.py          점검 1회
#   python watchdog06.py --dry    재실행하지 않고 판정만 출력
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
HEARTBEAT, STATE, MEMO = RESULTS / "heartbeat.json", RESULTS / "state06.json", RESULTS / "watchdog_state.json"
STALE_SEC = 90          # 정상이면 10초마다 갱신된다. 90초 = 9회 연속 누락
RELAUNCH_GAP_SEC = 180  # 재실행 직후 프로그램이 뜨는 동안 다시 띄우지 않는다
WATCH_FROM, WATCH_UNTIL, CLOSE_CHECK = "09:00", "15:34", "15:36"


def read(path):
    for _ in range(3):  # 쓰는 순간에 읽으면 실패할 수 있다
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.2)
    return None


def decide(now, hb, memo):
    """반환: (행동, 사유). 행동 = ok / relaunch / unclosed / idle"""
    hm, today = now.strftime("%H:%M"), now.strftime("%Y%m%d")
    if now.weekday() >= 5:
        return "idle", "주말"
    if hm >= CLOSE_CHECK:
        st = read(STATE) or {}
        if st.get("side") and memo.get("unclosed_alerted") != today:
            return "unclosed", f"장 마감 뒤 보유 {st['side'] * st['lots']}계약 (state06.json)"
        return "idle", "장 마감 뒤"
    if not (WATCH_FROM <= hm < WATCH_UNTIL):
        return "idle", "감시 시간 밖"
    if hb and hb.get("day") == today and hb.get("ended"):
        return "ok", "오늘 정상 종료"
    age = (now - datetime.fromisoformat(hb["ts"])).total_seconds() if hb and hb.get("day") == today else None
    if age is not None and age <= STALE_SEC:
        return "ok", f"heartbeat {age:.0f}초 전"
    last = memo.get("relaunch_at")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < RELAUNCH_GAP_SEC:
        return "ok", "재실행 직후 대기"
    return "relaunch", "오늘 heartbeat 없음" if age is None else f"heartbeat {age:.0f}초 끊김"


def main():
    from alert import alert
    now = datetime.now()
    hb, memo = read(HEARTBEAT), read(MEMO) or {}
    act, why = decide(now, hb, memo)
    rec = {"ts": now.isoformat(timespec="seconds"), "action": act, "why": why, "hb": hb}
    if act == "relaunch" and "--dry" not in sys.argv:
        if hb and hb.get("day") == now.strftime("%Y%m%d"):  # 살아 있는데 기록이 멈췄으면 종료하고 새로 띄운다
            from procs import kill_trade
            rec["killed"] = kill_trade(hb["pid"])  # 명령줄이 trade06 인 프로세스만 종료
        subprocess.Popen(["cmd", "/c", str(HERE / "run_trade06.bat")], cwd=HERE,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        memo["relaunch_at"] = now.isoformat(timespec="seconds")
        alert(f"감시: {why}. 자동매매 프로그램을 다시 실행함")
    elif act == "unclosed" and "--dry" not in sys.argv:
        memo["unclosed_alerted"] = now.strftime("%Y%m%d")
        alert(f"감시: {why}. 직접 확인 필요")
    MEMO.write_text(json.dumps(memo), encoding="utf-8")
    with open(RESULTS / f"watchdog_{now:%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(rec)


def selfcheck():
    d = datetime(2026, 11, 23, 10, 0, 0)
    fresh = {"ts": "2026-11-23T09:59:30", "day": "20261123", "pid": 1, "ended": False}
    assert decide(d, fresh, {})[0] == "ok"
    assert decide(d, {**fresh, "ts": "2026-11-23T09:58:00"}, {})[0] == "relaunch"         # 120초 끊김
    assert decide(d, None, {})[0] == "relaunch"                                           # 오늘 시작 안 함
    assert decide(d, {**fresh, "day": "20261120"}, {})[0] == "relaunch"                   # 어제 기록뿐
    assert decide(d, None, {"relaunch_at": "2026-11-23T09:58:30"})[0] == "ok"             # 재실행 90초 뒤
    assert decide(d, {**fresh, "ts": "2026-11-23T09:00:00", "ended": True}, {})[0] == "ok"  # 정상 종료
    assert decide(d.replace(hour=8, minute=55), None, {})[0] == "idle"
    assert decide(datetime(2026, 11, 21, 10, 0), None, {})[0] == "idle"                   # 토요일


if __name__ == "__main__":
    selfcheck()
    main()
