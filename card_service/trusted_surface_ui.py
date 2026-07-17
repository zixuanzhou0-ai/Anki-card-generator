from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from card_service.credentials import CredentialStore, CredentialStoreError
from card_service.storage import AtomicJsonStore


def read_request(path: Path) -> dict[str, Any]:
    value = json.loads(sys.stdin.read())
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("Invalid trusted surface request")
    if value.get("surface") not in {"local_settings", "consent"}:
        raise ValueError("Unknown trusted surface")
    session_ref = str(value.get("sessionRef") or "")
    expected_response = (path.parent.parent / "responses" / f"{session_ref}.json").resolve()
    if path.name != f"{session_ref}.json" or Path(str(value.get("responsePath") or "")) != expected_response:
        raise ValueError("Trusted surface request path mismatch")
    if value["surface"] == "local_settings":
        expected_credentials = (path.parent.parent / "credentials").resolve()
        if Path(str(value.get("credentialStateDir") or "")) != expected_credentials:
            raise ValueError("Trusted credential state path mismatch")
    return value


def write_response(request: dict[str, Any], state: str, **extra: Any) -> None:
    response_path = Path(str(request["responsePath"]))
    if not response_path.is_absolute():
        raise ValueError("Trusted surface response path must be absolute")
    AtomicJsonStore._write_atomic(
        response_path,
        {
            "schemaVersion": 1,
            "sessionRef": request["sessionRef"],
            "requestNonce": request["requestNonce"],
            "state": state,
            **extra,
        },
    )


def show_local_settings(request: dict[str, Any]) -> None:
    root = tk.Tk()
    root.title("Codex Study · 本地凭据设置")
    root.geometry("560x330")
    root.minsize(500, 300)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="配置本地服务凭据", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text="凭据直接保存到 Windows 凭据管理器，不会进入对话、MCP 或任务日志。", wraplength=500).pack(anchor="w", pady=(8, 20))
    ttk.Label(frame, text=f"配置：{request['profileRef']}  ·  {request['capability']}").pack(anchor="w")
    secret = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=secret, show="●", font=("Segoe UI", 12))
    entry.pack(fill="x", pady=(10, 18), ipady=7)
    status = ttk.Label(frame, text="")
    status.pack(anchor="w")

    def finish(state: str, **extra: Any) -> None:
        write_response(request, state, **extra)
        secret.set("")
        entry.delete(0, "end")
        root.destroy()

    def save() -> None:
        value = secret.get()
        if not value:
            status.configure(text="请输入凭据。")
            return
        try:
            store = CredentialStore(state_dir=Path(request["credentialStateDir"]))
            metadata = store.set_secret(str(request["profileRef"]), value)
        except (CredentialStoreError, OSError) as error:
            status.configure(text=f"保存失败：{error}")
            return
        finally:
            value = ""
        finish("completed", credential=metadata)

    def remove() -> None:
        if not messagebox.askyesno("移除凭据", "确定要移除这个本地凭据吗？", parent=root):
            return
        try:
            store = CredentialStore(state_dir=Path(request["credentialStateDir"]))
            metadata = store.delete_secret(str(request["profileRef"]))
        except (CredentialStoreError, OSError) as error:
            status.configure(text=f"移除失败：{error}")
            return
        finish("completed", credential=metadata)

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")
    ttk.Button(buttons, text="取消", command=lambda: finish("cancelled")).pack(side="right")
    ttk.Button(buttons, text="移除凭据", command=remove).pack(side="left")
    ttk.Button(buttons, text="保存凭据", command=save).pack(side="right", padx=(0, 10))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancelled"))
    entry.focus_set()
    root.mainloop()


def show_consent(request: dict[str, Any]) -> None:
    root = tk.Tk()
    root.title("Codex Study · 本地确认")
    root.geometry("620x360")
    root.minsize(540, 320)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=str(request["title"]), font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text=str(request["summary"]), wraplength=560, justify="left").pack(anchor="w", pady=(14, 20))
    ttk.Label(frame, text="只有这个本地窗口中的真实点击才会被记录；对话里的“我同意”不会替代它。", wraplength=560).pack(anchor="w")

    def finish(state: str) -> None:
        write_response(request, state, userGestureRecorded=state in {"approved", "declined"})
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")
    ttk.Button(buttons, text="拒绝", command=lambda: finish("declined")).pack(side="right")
    ttk.Button(buttons, text="确认", command=lambda: finish("approved")).pack(side="right", padx=(0, 10))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancelled"))
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=("local_settings", "consent"))
    parser.add_argument("request_path", type=Path)
    arguments = parser.parse_args()
    request = read_request(arguments.request_path.resolve(strict=True))
    if request["surface"] != arguments.surface:
        raise SystemExit("trusted surface request kind mismatch")
    if arguments.surface == "local_settings":
        show_local_settings(request)
    else:
        show_consent(request)


if __name__ == "__main__":
    main()
