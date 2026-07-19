from __future__ import annotations

import argparse
import json
import re
import sys
import tkinter as tk
import urllib.parse
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from card_service.credentials import CredentialStore, CredentialStoreError
from card_service.storage import AtomicJsonStore
from card_service.trusted_surface_auth import (
    decode_response_key,
    seal_private_payload,
    sign_response,
)


def read_request(path: Path) -> dict[str, Any]:
    value = json.loads(sys.stdin.read())
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("Invalid trusted surface request")
    if value.get("surface") not in {
        "local_settings",
        "consent",
        "local_resource_picker",
        "network_resource_input",
        "authorization_manager",
    }:
        raise ValueError("Unknown trusted surface")
    session_ref = str(value.get("sessionRef") or "")
    expected_response = (path.parent.parent / "responses" / f"{session_ref}.json").resolve()
    if path.name != f"{session_ref}.json" or Path(str(value.get("responsePath") or "")) != expected_response:
        raise ValueError("Trusted surface request path mismatch")
    if value["surface"] == "local_resource_picker" and value.get("selectionKind") not in {
        "file", "directory", "output_directory"
    }:
        raise ValueError("Unknown local resource selection kind")
    if value["surface"] == "network_resource_input" and value.get(
        "sourceKind"
    ) not in {"public_video", "web", "podcast", "other"}:
        raise ValueError("Unknown network resource kind")
    if value["surface"] == "local_settings":
        expected_credentials = (path.parent.parent / "credentials").resolve()
        if Path(str(value.get("credentialStateDir") or "")) != expected_credentials:
            raise ValueError("Trusted credential state path mismatch")
    if value["surface"] == "authorization_manager":
        if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("audienceDigest") or "")):
            raise ValueError("Trusted authorization audience is invalid")
        items = value.get("authorizationItems")
        if not isinstance(items, list) or not 1 <= len(items) <= 256:
            raise ValueError("Trusted authorization items are invalid")
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "selectionRef",
                "kind",
                "title",
                "detail",
                "state",
            }:
                raise ValueError("Trusted authorization item is invalid")
            selection_ref = item.get("selectionRef")
            if (
                not isinstance(selection_ref, str)
                or not re.fullmatch(r"authsel_[A-Za-z0-9_-]{32}", selection_ref)
                or selection_ref in seen
                or item.get("kind")
                not in {
                    "local_resource",
                    "network_resource",
                    "anki_import",
                    "broker_authorization",
                    "operation_approval",
                }
                or item.get("state") not in {"active", "approved", "pending"}
                or not isinstance(item.get("title"), str)
                or not 1 <= len(item["title"].strip()) <= 160
                or not isinstance(item.get("detail"), str)
                or not 1 <= len(item["detail"].strip()) <= 500
            ):
                raise ValueError("Trusted authorization item is invalid")
            seen.add(selection_ref)
    decode_response_key(str(value.get("responseAuthKey") or ""))
    return value


def write_response(request: dict[str, Any], state: str, **extra: Any) -> None:
    response_path = Path(str(request["responsePath"]))
    if not response_path.is_absolute():
        raise ValueError("Trusted surface response path must be absolute")
    response_key = decode_response_key(str(request.get("responseAuthKey") or ""))
    AtomicJsonStore._write_atomic(
        response_path,
        sign_response(
            {
            "schemaVersion": 1,
            "sessionRef": request["sessionRef"],
            "requestNonce": request["requestNonce"],
            "state": state,
            **extra,
            },
            response_key,
        ),
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


def show_local_resource_picker(request: dict[str, Any]) -> None:
    root = tk.Tk()
    root.title("Codex Study · 选择本地资源")
    root.geometry("620x360")
    root.minsize(540, 320)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    kind = str(request["selectionKind"])
    kind_label = {
        "file": "文件",
        "directory": "输入文件夹",
        "output_directory": "输出文件夹",
    }[kind]
    ttk.Label(
        frame,
        text=f"选择{kind_label}",
        font=("Microsoft YaHei UI", 18, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "只有你在这个本地窗口中选择的资源会被授权。完整路径不会进入对话、MCP、任务日志或响应文件。"
        ),
        wraplength=560,
    ).pack(anchor="w", pady=(10, 18))
    ttk.Label(
        frame,
        text=str(request.get("scopeSummary") or "本次授权仅用于当前制卡任务。"),
        wraplength=560,
    ).pack(anchor="w")
    status = ttk.Label(frame, text="尚未选择。")
    status.pack(anchor="w", pady=(18, 0))

    def finish(state: str, selected_path: str | None = None) -> None:
        extra: dict[str, Any] = {"userGestureRecorded": state == "selected"}
        if state == "selected" and selected_path:
            response_key = decode_response_key(str(request.get("responseAuthKey") or ""))
            extra["privatePayload"] = seal_private_payload(
                {"schemaVersion": 1, "selectedPath": selected_path},
                response_key,
                session_ref=str(request["sessionRef"]),
                request_nonce=str(request["requestNonce"]),
                surface="local_resource_picker",
            )
        write_response(request, state, **extra)
        root.destroy()

    def choose() -> None:
        if kind == "file":
            selected = filedialog.askopenfilename(parent=root, title="选择学习素材")
        else:
            selected = filedialog.askdirectory(
                parent=root,
                title="选择输入文件夹" if kind == "directory" else "选择输出文件夹",
                mustexist=True,
            )
        if not selected:
            status.configure(text="没有选择任何资源。")
            return
        finish("selected", selected)

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")
    ttk.Button(buttons, text="取消", command=lambda: finish("cancelled")).pack(side="right")
    ttk.Button(buttons, text=f"选择{kind_label}", command=choose).pack(side="right", padx=(0, 10))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancelled"))
    root.mainloop()


def show_consent(request: dict[str, Any]) -> None:
    root = tk.Tk()
    root.title("Codex Study · 本地确认")
    root.geometry("720x520")
    root.minsize(600, 420)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=str(request["title"]), font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    summary_frame = ttk.Frame(frame)
    summary_frame.pack(fill="both", expand=True, pady=(14, 16))
    summary = tk.Text(
        summary_frame,
        wrap="word",
        height=12,
        font=("Microsoft YaHei UI", 11),
        padx=12,
        pady=10,
        relief="solid",
        borderwidth=1,
        takefocus=True,
    )
    scrollbar = ttk.Scrollbar(summary_frame, orient="vertical", command=summary.yview)
    summary.configure(yscrollcommand=scrollbar.set)
    summary.insert("1.0", str(request["summary"]))
    summary.configure(state="disabled")
    summary.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    ttk.Label(
        frame,
        text="请核对上方全部范围。只有这个本地窗口中的真实点击才会被记录；对话里的“我同意”不会替代它。",
        wraplength=650,
    ).pack(anchor="w", pady=(0, 14))

    def finish(state: str) -> None:
        write_response(request, state, userGestureRecorded=state in {"approved", "declined"})
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")
    decline_button = ttk.Button(
        buttons, text="拒绝", command=lambda: finish("declined")
    )
    decline_button.pack(side="right")
    approve_label = (
        "授权并继续"
        if request.get("authorizationKind") == "broker_startup"
        else "确认导入"
        if request.get("confirmationKind") == "anki_import"
        else "批准一次验证"
        if request.get("confirmationKind") == "operation_intent"
        else "确认"
    )
    approve_button = ttk.Button(
        buttons, text=approve_label, command=lambda: finish("approved")
    )
    approve_button.pack(side="right", padx=(0, 10))
    decline_button.bind("<Return>", lambda _event: finish("declined"))
    approve_button.bind("<Return>", lambda _event: finish("approved"))
    root.after_idle(decline_button.focus_set)
    root.bind("<Escape>", lambda _event: finish("cancelled"))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancelled"))
    root.mainloop()


def show_network_resource_input(request: dict[str, Any]) -> None:
    root = tk.Tk()
    root.title("Codex Study · 添加网络素材")
    root.geometry("720x500")
    root.minsize(620, 440)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="添加网络学习素材",
        font=("Microsoft YaHei UI", 18, "bold"),
    ).pack(anchor="w")
    kind_label = {
        "public_video": "公开视频",
        "web": "网页",
        "podcast": "播客",
        "other": "其他 HTTPS 资源",
    }[str(request["sourceKind"])]
    ttk.Label(
        frame,
        text=(
            f"来源类型：{kind_label}\n"
            "请在此本地窗口粘贴地址。完整地址不会进入 Codex 对话、MCP 参数或持久日志。"
        ),
        wraplength=660,
        justify="left",
    ).pack(anchor="w", pady=(10, 18))
    ttk.Label(frame, text="HTTPS 地址").pack(anchor="w")
    raw_url = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=raw_url, font=("Segoe UI", 11))
    entry.pack(fill="x", pady=(6, 10), ipady=5)
    preview = ttk.Label(
        frame,
        text="尚未输入地址。",
        wraplength=660,
        justify="left",
    )
    preview.pack(anchor="w", fill="x")
    ttk.Label(
        frame,
        text=(
            "仅支持公网 HTTPS（443）。不会携带浏览器 Cookie、Authorization、系统代理或"
            "登录状态；带查询参数的地址会按敏感输入处理，且只保留在当前服务进程内存中。"
        ),
        wraplength=660,
        justify="left",
    ).pack(anchor="w", pady=(18, 14))
    status = ttk.Label(frame, text="")
    status.pack(anchor="w", fill="x")
    authorize_button: ttk.Button
    finished = False

    def validate() -> tuple[bool, str]:
        value = raw_url.get().strip()
        if not value or len(value) > 16 * 1024 or any(
            ord(character) < 0x20 or character.isspace() for character in value
        ):
            return False, "请输入完整、无空格的 HTTPS 地址。"
        try:
            parsed = urllib.parse.urlsplit(value)
            port = parsed.port
        except ValueError:
            return False, "地址格式无效。"
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or bool(parsed.fragment)
        ):
            return False, "仅允许不含账号、密码或片段的公网 HTTPS（443）地址。"
        host = parsed.hostname.rstrip(".").casefold()
        query_notice = "；检测到查询参数，将按敏感输入处理" if parsed.query else ""
        return True, f"将授权访问：https://{host}{query_notice}。"

    def refresh(*_args: object) -> None:
        valid, message = validate()
        preview.configure(text=message)
        authorize_button.configure(state="normal" if valid else "disabled")

    def finish(state: str) -> None:
        nonlocal finished
        if finished:
            return
        if state == "selected":
            valid, message = validate()
            if not valid:
                status.configure(text=message)
                entry.focus_set()
                return
        finished = True
        extra: dict[str, Any] = {"userGestureRecorded": state == "selected"}
        if state == "selected":
            response_key = decode_response_key(
                str(request.get("responseAuthKey") or "")
            )
            extra["privatePayload"] = seal_private_payload(
                {"schemaVersion": 1, "rawUrl": raw_url.get().strip()},
                response_key,
                session_ref=str(request["sessionRef"]),
                request_nonce=str(request["requestNonce"]),
                surface="network_resource_input",
            )
        write_response(request, state, **extra)
        raw_url.set("")
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")
    cancel_button = ttk.Button(
        buttons, text="取消", command=lambda: finish("cancelled")
    )
    cancel_button.pack(side="right")
    authorize_button = ttk.Button(
        buttons,
        text="授权此地址",
        command=lambda: finish("selected"),
        state="disabled",
    )
    authorize_button.pack(side="right", padx=(0, 10))
    raw_url.trace_add("write", refresh)
    cancel_button.bind("<Return>", lambda _event: finish("cancelled"))
    authorize_button.bind("<Return>", lambda _event: finish("selected"))
    root.bind("<Escape>", lambda _event: finish("cancelled"))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancelled"))
    root.after_idle(cancel_button.focus_set)
    root.mainloop()


def show_authorization_manager(request: dict[str, Any]) -> None:
    root = tk.Tk()
    root.title("Codex Study · 授权管理")
    root.geometry("820x600")
    root.minsize(680, 500)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="管理当前会话的授权",
        font=("Microsoft YaHei UI", 18, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "请选择要停止继续使用的授权。撤销只阻止后续访问；已经完成的模型调用、"
            "文件读取或 Anki 写入不会被回滚。授权的私有标识不会进入对话。"
        ),
        wraplength=750,
    ).pack(anchor="w", pady=(10, 18))

    table_frame = ttk.Frame(frame)
    table_frame.pack(fill="both", expand=True)
    table = ttk.Treeview(
        table_frame,
        columns=("kind", "title", "detail", "state"),
        show="headings",
        selectmode="extended",
        height=12,
    )
    table.heading("kind", text="类型")
    table.heading("title", text="授权")
    table.heading("detail", text="范围")
    table.heading("state", text="状态")
    table.column("kind", width=105, minwidth=90, stretch=False)
    table.column("title", width=185, minwidth=140, stretch=False)
    table.column("detail", width=390, minwidth=220, stretch=True)
    table.column("state", width=80, minwidth=70, stretch=False)
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scrollbar.set)
    kind_labels = {
        "local_resource": "本地资源",
        "network_resource": "网络资源",
        "anki_import": "Anki 导入",
        "broker_authorization": "远程服务",
        "operation_approval": "操作批准",
    }
    state_labels = {"active": "使用中", "approved": "已批准", "pending": "待执行"}
    for item in request["authorizationItems"]:
        table.insert(
            "",
            "end",
            iid=str(item["selectionRef"]),
            values=(
                kind_labels[str(item["kind"])],
                str(item["title"]),
                str(item["detail"]),
                state_labels[str(item["state"])],
            ),
        )
    table.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    status = ttk.Label(frame, text="请选择至少一项。")
    status.pack(anchor="w", pady=(12, 8))
    revoke_button: ttk.Button

    finished = False

    def finish(state: str, selected_refs: list[str] | None = None) -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        extra: dict[str, Any] = {"userGestureRecorded": state == "approved"}
        if state == "approved" and selected_refs:
            response_key = decode_response_key(
                str(request.get("responseAuthKey") or "")
            )
            extra["privatePayload"] = seal_private_payload(
                {"schemaVersion": 1, "selectedRefs": selected_refs},
                response_key,
                session_ref=str(request["sessionRef"]),
                request_nonce=str(request["requestNonce"]),
                surface="authorization_manager",
            )
        write_response(request, state, **extra)
        root.destroy()

    def revoke_selected() -> None:
        selected_refs = list(table.selection())
        if not selected_refs:
            status.configure(text="请先选择至少一项要撤销的授权。")
            table.focus_set()
            return
        if not messagebox.askyesno(
            "确认撤销",
            (
                f"确定撤销选中的 {len(selected_refs)} 项授权吗？\n\n"
                "这会阻止后续访问，但不会回滚已经完成的调用或写入。"
            ),
            parent=root,
            default=messagebox.NO,
        ):
            return
        finish("approved", selected_refs)

    def update_selection_status(_event: tk.Event[Any] | None = None) -> None:
        selected_count = len(table.selection())
        revoke_button.configure(state="normal" if selected_count else "disabled")
        status.configure(
            text=(
                f"已选择 {selected_count} 项。"
                if selected_count
                else "请选择至少一项。"
            )
        )

    def select_all(_event: tk.Event[Any] | None = None) -> str:
        table.selection_set(table.get_children())
        update_selection_status()
        return "break"

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom", pady=(6, 0))
    ttk.Button(buttons, text="取消", command=lambda: finish("cancelled")).pack(
        side="right"
    )
    revoke_button = ttk.Button(
        buttons,
        text="撤销所选授权",
        command=revoke_selected,
        state="disabled",
    )
    revoke_button.pack(side="right", padx=(0, 10))
    table.bind("<<TreeviewSelect>>", update_selection_status)
    table.bind("<Control-a>", select_all)
    table.bind("<Control-A>", select_all)
    table.bind("<Return>", lambda _event: revoke_selected())
    root.bind("<Escape>", lambda _event: finish("cancelled"))
    root.protocol("WM_DELETE_WINDOW", lambda: finish("cancelled"))
    children = table.get_children()
    if children:
        table.focus(children[0])
    table.focus_set()
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "surface",
        choices=(
            "local_settings",
            "consent",
            "local_resource_picker",
            "network_resource_input",
            "authorization_manager",
        ),
    )
    parser.add_argument("request_path", type=Path)
    arguments = parser.parse_args()
    request = read_request(arguments.request_path.resolve(strict=True))
    if request["surface"] != arguments.surface:
        raise SystemExit("trusted surface request kind mismatch")
    if arguments.surface == "local_settings":
        show_local_settings(request)
    elif arguments.surface == "consent":
        show_consent(request)
    elif arguments.surface == "authorization_manager":
        show_authorization_manager(request)
    elif arguments.surface == "network_resource_input":
        show_network_resource_input(request)
    else:
        show_local_resource_picker(request)


if __name__ == "__main__":
    main()
