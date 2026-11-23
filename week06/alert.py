# 알림: 기록(results/alerts.jsonl) + 윈도우 화면 알림(풍선 알림). 화면 알림은 실패해도 매매를 멈추지 않는다
#   python alert.py "시험 메시지"   화면 알림이 뜨는지 확인
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ALERTS = Path(__file__).resolve().parent / "results" / "alerts.jsonl"
PS = ("Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
      "$n.Icon = [System.Drawing.SystemIcons]::Warning; $n.Visible = $true; "
      "$n.ShowBalloonTip(15000, 'NH 6주차 자동매매', $env:NH_ALERT, 'Warning'); Start-Sleep 15; $n.Dispose()")


def alert(msg, journal=None):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "msg": msg, "src": Path(sys.argv[0]).name}
    ALERTS.parent.mkdir(exist_ok=True)
    with open(ALERTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if journal:
        journal("alert", msg=msg)
    else:
        print("[알림]", msg, flush=True)
    try:  # 메시지는 환경변수로 넘긴다 (명령줄 따옴표 문제 방지). 기다리지 않는다
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", PS],
                         env={**os.environ, "NH_ALERT": msg}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass


if __name__ == "__main__":
    alert(sys.argv[1] if len(sys.argv) > 1 else "알림 시험")
