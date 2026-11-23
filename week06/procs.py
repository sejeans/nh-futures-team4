# 6주차 자동매매 프로세스만 찾아서 종료한다 (감시 프로그램과 중단 시험용)
# PID 는 재사용되므로 번호만 믿지 않고 명령줄이 trade06.py 또는 run_trade06.bat 인지 확인한 뒤 종료한다
import json
import subprocess

PS = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
      "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='cmd.exe'\" | "
      "Select-Object ProcessId, ParentProcessId, Name, CommandLine | ConvertTo-Json -Compress")
HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def table():
    out = subprocess.run(["powershell", "-NoProfile", "-Command", PS], capture_output=True, encoding="utf-8",
                         errors="replace", timeout=30, creationflags=HIDE).stdout.strip()
    rows = json.loads(out) if out else []
    return {p["ProcessId"]: p for p in (rows if isinstance(rows, list) else [rows])}


def ours(p):
    if not p:
        return False
    name, cmd = p["Name"].lower(), p.get("CommandLine") or ""
    return (name == "python.exe" and "trade06.py" in cmd) or (name == "cmd.exe" and "run_trade06.bat" in cmd)


def tree_root(pid, procs):
    """pid 가 우리 프로세스가 아니면 None. 맞으면 맨 위 조상(bat 을 실행한 cmd)의 pid"""
    if not ours(procs.get(pid)):
        return None
    seen = {pid}
    while True:
        up = procs[pid]["ParentProcessId"]
        if up in seen or not ours(procs.get(up)):
            return pid
        seen.add(up)
        pid = up


def kill_trade(pid):
    """실행 창을 닫은 것처럼 cmd 와 파이썬을 함께 종료한다. 반환: 종료한 맨 위 pid 또는 None"""
    root = tree_root(int(pid), table())
    if root:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(root)], capture_output=True, creationflags=HIDE)
    return root
