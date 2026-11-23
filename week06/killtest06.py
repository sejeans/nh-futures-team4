# 감시 프로그램 작동 시험: 정한 날 한 번, 실행 창을 닫은 것과 같게 자동매매 프로그램을 일부러 종료한다
#   python killtest06.py 20261123
# 첫 진입 가능 시각(10:30) 전에 실행하고, 보유나 미체결이 있으면 종료하지 않는다. 주문은 내지 않는다
# 이 시험으로 생긴 중단은 실제 장애가 아니므로 기록과 보고서에 의도한 시험이라고 남긴다
import json
import sys
from datetime import datetime

from alert import alert
from procs import kill_trade
from watchdog06 import HEARTBEAT, RESULTS, read


def refuse(now, hb, day):
    if f"{now:%Y%m%d}" != day:
        return "시험 날짜가 아님"
    if not hb or hb.get("day") != day or hb.get("ended"):
        return "실행 중인 프로그램이 없음"
    if hb.get("side") or hb.get("pending"):
        return "보유 또는 미체결이 있음"
    if (now - datetime.fromisoformat(hb["ts"])).total_seconds() > 30:
        return "heartbeat 가 이미 끊겨 있음"
    return None


def main():
    now, hb = datetime.now(), read(HEARTBEAT)
    why = refuse(now, hb, sys.argv[1] if len(sys.argv) > 1 else "")
    root = None if why else kill_trade(hb["pid"])
    rec = {"ts": now.isoformat(timespec="seconds"), "event": "intentional_kill_test", "killed_root": root,
           "skipped": why or (None if root else "프로세스를 찾지 못함"), "hb": hb}
    with open(RESULTS / f"killtest_{now:%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    alert(f"중단 시험(의도적): {'자동매매 종료, 감시의 재실행 대기' if root else rec['skipped']}")


if __name__ == "__main__":
    main()
