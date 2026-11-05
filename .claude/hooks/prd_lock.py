# -*- coding: utf-8 -*-
"""PRD 자물쇠 — PreToolUse 훅.

Edit/Write 도구가 이 프로젝트의 PRD.md 를 건드리려 하면
1) 종료 코드 2로 도구 실행을 막고
2) 화면 가운데에 항상 맨 앞으로 경고창을 띄우고
3) stderr 로 "제안만 하라"는 이유를 AI에게 돌려보낸다.
다른 파일은 아무 출력 없이 통과(종료 코드 0)시킨다.
"""
import json
import os
import subprocess
import sys

LOCKED_NAME = "PRD.md"
DIALOG_TITLE = "PRD 자물쇠"
DIALOG_TEXT = "PRD.md 는 잠겨 있습니다"
REASON = "PRD.md 는 잠겨 있으니 고치지 말고 바꿀 내용을 제안만 하라"



def show_dialog():
    """별도 프로세스에서 실행되는 경고창. 화면 가운데, 항상 맨 앞."""
    import tkinter as tk

    root = tk.Tk()
    root.title(DIALOG_TITLE)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = tk.Frame(root, padx=28, pady=20)
    frame.pack()
    tk.Label(frame, text="\U0001F512", font=("Segoe UI Emoji", 28)).pack()
    tk.Label(frame, text=DIALOG_TEXT, font=("Malgun Gothic", 13)).pack(pady=(8, 16))
    tk.Button(frame, text="확인", width=12, command=root.destroy).pack()
    root.bind("<Return>", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    root.lift()
    root.focus_force()
    root.after(200, lambda: root.attributes("-topmost", True))
    root.mainloop()


def spawn_dialog():
    """훅 본체를 기다리게 하지 않도록 경고창을 분리된 프로세스로 띄운다."""
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    try:
        subprocess.Popen([exe, os.path.abspath(__file__), "--dialog"], **kwargs)
    except Exception:
        pass  # 창이 안 떠도 차단 자체는 그대로 진행  # 창이 안 떠도 차단 자체는 그대로 진행


def is_locked_target(file_path, project_dir):
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    if os.path.basename(normalized).lower() != LOCKED_NAME.lower():
        return False
    if not project_dir:
        return True  # 프로젝트 루트를 모르면 이름만으로 판정
    target = os.path.normcase(os.path.realpath(os.path.join(project_dir, LOCKED_NAME)))
    candidate = normalized
    if not os.path.isabs(candidate):
        candidate = os.path.join(project_dir, candidate)
    candidate = os.path.normcase(os.path.realpath(candidate))
    return candidate == target


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--dialog":
        show_dialog()
        return 0

    for stream in (sys.stdin, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # 입력을 못 읽으면 막지 않고 통과

    if data.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return 0
    if data.get("tool_name") not in ("Edit", "Write"):
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path", "")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ""

    if not is_locked_target(file_path, project_dir):
        return 0

    spawn_dialog()
    sys.stderr.write(REASON + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
