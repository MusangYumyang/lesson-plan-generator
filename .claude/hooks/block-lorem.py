# -*- coding: utf-8 -*-
"""block-lorem — PreToolUse 훅.

Edit/Write 도구가 이 프로젝트의 app.py 에 수강생 호칭 "어르신" 을 새로 넣으려 하면
1) 종료 코드 2로 도구 실행을 막고
2) 화면 가운데에 항상 맨 앞으로 경고창을 띄우고
3) stderr 로 "수강생/여러분으로 바꿔 다시 시도하라"는 이유를 AI에게 돌려보낸다.

보지 않는 것:
- app.py 가 아닌 파일
- 따옴표로 감싼 "어르신", '어르신', `어르신` (쓰지 말라는 금지 문장)
- 이미 있던 "어르신"을 줄이거나 그대로 두는 편집
"""
import json
import os
import re
import subprocess
import sys

TARGET_NAME = "app.py"
BANNED = "어르신"
QUOTED = re.compile(r"""["'`]어르신["'`]""")
DIALOG_TITLE = "block-lorem"
DIALOG_TEXT = "수강생 호칭으로 '어르신'을 쓰지 않습니다"
REASON = "호칭은 '수강생' 또는 '여러분'으로 통일한다. '어르신'을 바꿔서 다시 시도하라"


def show_dialog():
    import tkinter as tk

    root = tk.Tk()
    root.title(DIALOG_TITLE)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = tk.Frame(root, padx=28, pady=20)
    frame.pack()
    tk.Label(frame, text="✋", font=("Segoe UI Emoji", 28)).pack()
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
        pass  # 창이 안 떠도 차단 자체는 그대로 진행


def is_target_file(file_path, project_dir):
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    if os.path.basename(normalized).lower() != TARGET_NAME.lower():
        return False
    if not project_dir:
        return True
    target = os.path.normcase(os.path.realpath(os.path.join(project_dir, TARGET_NAME)))
    candidate = normalized
    if not os.path.isabs(candidate):
        candidate = os.path.join(project_dir, candidate)
    candidate = os.path.normcase(os.path.realpath(candidate))
    return candidate == target


def count_banned(text):
    """따옴표로 감싼 것(금지 문장)은 빼고 '어르신' 개수를 센다."""
    if not text:
        return 0
    return QUOTED.sub("", text).count(BANNED)


def adds_banned_text(tool_name, tool_input):
    if tool_name == "Write":
        return count_banned(tool_input.get("content")) > 0
    if tool_name == "Edit":
        return count_banned(tool_input.get("new_string")) > count_banned(tool_input.get("old_string"))
    return False


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
    tool_name = data.get("tool_name")
    if tool_name not in ("Edit", "Write"):
        return 0

    tool_input = data.get("tool_input") or {}
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ""

    if not is_target_file(tool_input.get("file_path", ""), project_dir):
        return 0
    if not adds_banned_text(tool_name, tool_input):
        return 0

    spawn_dialog()
    sys.stderr.write(REASON + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
