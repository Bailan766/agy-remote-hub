"""
Conversational Agent Runner (OpenClaw-style command & chat router)
Handles IM messages (Telegram / Feishu / QQ) and Web Chat requests:
- Built-in commands: /help, /usage, /quota, /status, /screen, /desktop, /approve, /cancel, /cd, /pwd, /new, /mode
- Conversational execution via Antigravity CLI (`agy -p`) with session resume,
  or optional fallback to desktop Antigravity window injection.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from quota_monitor import format_quota_report, get_antigravity_quota


@dataclass
class AgentReply:
    text: str
    image_bytes: Optional[bytes] = None
    image_name: str = "screenshot.jpg"


@dataclass
class ChatSession:
    chat_key: str
    cwd: str
    conversation_id: Optional[str] = None
    mode: str = "auto"
    model: str = ""


class AgentRunner:
    def __init__(
        self,
        config_getter: Callable[[], Dict[str, Any]],
        screenshot_fn: Optional[Callable[[], bytes]] = None,
        desktop_send_fn: Optional[Callable[[str, bool], Dict[str, Any]]] = None,
        desktop_action_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        conversations_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        config_saver: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.get_config = config_getter
        self.save_config_fn = config_saver
        self.screenshot_fn = screenshot_fn
        self.desktop_send_fn = desktop_send_fn
        self.desktop_action_fn = desktop_action_fn
        self.conversations_fn = conversations_fn
        self.sessions: Dict[str, ChatSession] = {}

    def _get_session(self, chat_key: str) -> ChatSession:
        cfg = self.get_config()
        if chat_key not in self.sessions:
            default_cwd = cfg.get("workspace_dir") or str(Path.home())
            if not Path(default_cwd).is_dir():
                default_cwd = str(Path.home())
            self.sessions[chat_key] = ChatSession(
                chat_key=chat_key,
                cwd=default_cwd,
                mode=cfg.get("agy_mode", "auto"),
                model=(cfg.get("agy_model") or "").strip(),
            )
        return self.sessions[chat_key]

    def set_default_model(self, model_name: str, chat_key: Optional[str] = None) -> None:
        clean = (model_name or "").strip()
        cfg = self.get_config()
        cfg["agy_model"] = clean
        if self.save_config_fn:
            self.save_config_fn(cfg)
        if chat_key and chat_key in self.sessions:
            self.sessions[chat_key].model = clean
        for sess in self.sessions.values():
            sess.model = clean

    def _find_agy_bin(self) -> Optional[str]:
        cfg = self.get_config()
        custom = (cfg.get("agy_path") or "").strip()
        if custom and Path(custom).exists():
            return custom
        return shutil.which("agy")

    def _help_text(self) -> str:
        return (
            "🤖 **Antigravity Pocket 对话助手**\n\n"
            "直接发自然语言即可像 OpenClaw 一样远程执行任务；也支持以下快捷指令：\n\n"
            "📊 **状态、用量与模型**\n"
            "• `/usage` 或 `用量` — 查看各模型剩余额度与重置倒计时\n"
            "• `/models` — 查看可切换的模型列表（带序号与剩余额度）\n"
            "• `/model <序号或名称>` — 切换对话模型（`/model default` 恢复默认）\n"
            "• `/status` — 查看电脑状态、当前目录与最近会话\n"
            "• `/screen` 或 `截图` — 获取当前电脑桌面截图\n\n"
            "💬 **对话与工作区**\n"
            "• `/new` — 开启全新对话上下文\n"
            "• `/pwd` — 查看当前工作目录\n"
            "• `/cd <路径>` — 切换工作目录\n"
            "• `/mode <auto|accept-edits|plan|default>` — 切换 `agy` 执行模式\n\n"
            "🖥️ **桌面端窗口联动**\n"
            "• `/desktop <指令>` — 直接注入到电脑桌面的 Antigravity 窗口并回车\n"
            "• `/approve` 或 `同意` — 确认执行（桌面端按下回车）\n"
            "• `/cancel` — 取消当前弹窗（桌面端按下 Esc）"
        )

    def _handle_models(self, session: ChatSession, arg: str = "") -> AgentReply:
        data = get_antigravity_quota(include_cli_fallback=False)
        models = data.get("models") or []

        if not arg:
            current = session.model or "系统默认"
            lines = [f"🧠 **当前对话模型**：`{current}`"]
            if models:
                lines.append("\n可发送 `/model <序号>` 或 `/model <名称>` 切换：")
                for idx, m in enumerate(models, start=1):
                    mark = " ✅" if session.model in (m["model_id"], m["label"]) else ""
                    lines.append(f"`{idx}`. **{m['label']}** (`{m['model_id']}`) — 剩余 {m['remaining_pct']:.0f}%{mark}")
                lines.append("\n发送 `/model default` 可恢复默认模型。")
            else:
                lines.append(
                    "\n未检测到桌面端模型列表（可先打开 Antigravity 桌面端），"
                    "也可直接手动指定名称，例如：\n`/model gemini-4-neon`"
                )
            return AgentReply(text="\n".join(lines))

        lower_arg = arg.strip().lower()
        if lower_arg in ("default", "reset", "auto", "默认"):
            self.set_default_model("", session.chat_key)
            return AgentReply(text="✅ 已恢复为 Antigravity **系统默认模型**。")

        chosen = arg.strip()
        chosen_label = chosen
        if models:
            if chosen.isdigit():
                idx = int(chosen)
                if 1 <= idx <= len(models):
                    chosen = models[idx - 1]["model_id"]
                    chosen_label = models[idx - 1]["label"]
                else:
                    return AgentReply(text=f"❌ 序号超出范围（1 ~ {len(models)}），请发送 `/models` 查看列表。")
            else:
                matched = None
                for m in models:
                    if lower_arg in (m["model_id"].lower(), m["label"].lower()):
                        matched = m
                        break
                if not matched:
                    for m in models:
                        if lower_arg in m["model_id"].lower() or lower_arg in m["label"].lower():
                            matched = m
                            break
                if matched:
                    chosen = matched["model_id"]
                    chosen_label = matched["label"]

        self.set_default_model(chosen, session.chat_key)
        return AgentReply(text=f"✅ 已切换对话模型为：**{chosen_label}** (`{chosen}`)")

    def _handle_status(self, session: ChatSession) -> AgentReply:
        agy_bin = self._find_agy_bin()
        lines = [
            "🖥️ **电脑端运行状态**",
            f"• 主机名：`{socket.gethostname()}` ({platform.system()})",
            f"• 当前目录：`{session.cwd}`",
            f"• 当前模型：`{session.model or '系统默认'}`",
            f"• 执行模式：`{session.mode}`",
            f"• CLI (`agy`)：{'✅ 已就绪 (' + agy_bin + ')' if agy_bin else '❌ 未检测到（将使用桌面窗口注入模式）'}",
        ]
        if session.conversation_id:
            lines.append(f"• 当前会话 ID：`{session.conversation_id}`")

        if self.conversations_fn:
            try:
                convs = self.conversations_fn()
                if convs:
                    lines.append("\n🗂️ **最近 Antigravity 会话：**")
                    for c in convs[:3]:
                        lines.append(f"• [{c.get('status', '?')}] {c.get('title', '')}")
            except Exception:
                pass
        return AgentReply(text="\n".join(lines))

    def _run_agy_cli(self, session: ChatSession, prompt: str) -> AgentReply:
        agy_bin = self._find_agy_bin()
        if not agy_bin:
            cfg = self.get_config()
            im_cfg = cfg.get("im_bridge") or {}
            if im_cfg.get("fallback_to_desktop", True) and self.desktop_send_fn:
                try:
                    self.desktop_send_fn(prompt, True)
                    return AgentReply(
                        text=(
                            "📤 未检测到本地 `agy` CLI，已自动将指令注入到电脑桌面端 **Antigravity 窗口** 并提交。\n"
                            "💡 发送 `/screen` 可随时查看桌面最新画面，或发送 `/approve` 确认执行。"
                        )
                    )
                except Exception as exc:
                    return AgentReply(text=f"❌ 桌面端注入失败：{exc}")
            return AgentReply(
                text=(
                    "⚠️ 未检测到 `agy` CLI（Antigravity CLI）。\n"
                    "请先安装并登录 `agy`，或使用 `/desktop <指令>` 直接发送到桌面端窗口。"
                )
            )

        cmd = [agy_bin, "-p", prompt, "--output-format", "json"]
        if session.model:
            cmd.extend(["--model", session.model])
        if session.mode:
            cmd.extend(["--mode", session.mode])
        if session.conversation_id:
            cmd.extend(["--resume", session.conversation_id])

        kwargs: Dict[str, Any] = {
            "cwd": session.cwd,
            "capture_output": True,
            "text": True,
            "timeout": 300,
            "encoding": "utf-8",
            "errors": "ignore",
        }
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired:
            return AgentReply(text="⏱️ 任务执行超过 5 分钟超时。你可以发送 `/status` 或 `/screen` 检查进度。")
        except Exception as exc:
            return AgentReply(text=f"❌ 调用 `agy` 失败：{exc}")

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if not stdout and proc.returncode != 0:
            err_msg = stderr or f"退出码 {proc.returncode}"
            return AgentReply(text=f"❌ `agy` 执行出错：\n```\n{err_msg[:1500]}\n```")

        reply_text = stdout
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                conv_id = data.get("conversation_id") or data.get("session_id") or data.get("id")
                if conv_id:
                    session.conversation_id = str(conv_id)
                for key in ("response", "result", "content", "text", "message", "output"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        reply_text = val.strip()
                        break
        except Exception:
            pass

        if not reply_text:
            reply_text = stderr or "✅ 已执行完成（无文本输出）。"

        return AgentReply(text=reply_text)

    def handle_message(self, chat_key: str, raw_text: str) -> AgentReply:
        """Process a user message synchronously (call in worker thread for async loops)."""
        text = (raw_text or "").strip()
        if not text:
            return AgentReply(text="请发送具体指令，或发送 `/help` 查看帮助。")

        session = self._get_session(chat_key)
        lower = text.lower()

        if lower in ("/start", "/help", "帮助", "help"):
            return AgentReply(text=self._help_text())

        if lower in ("/usage", "/quota", "/credits", "/用量", "用量", "模型用量", "查看用量", "额度"):
            data = get_antigravity_quota(include_cli_fallback=True)
            return AgentReply(text=format_quota_report(data))

        if lower in ("/models", "/model", "模型", "模型列表", "切换模型"):
            return self._handle_models(session)

        if lower.startswith("/model "):
            return self._handle_models(session, text[7:].strip())

        if lower in ("/status", "/状态", "状态"):
            return self._handle_status(session)

        if lower in ("/screen", "/screenshot", "/截图", "截图", "截屏"):
            if not self.screenshot_fn:
                return AgentReply(text="⚠️ 当前环境未启用桌面截图功能。")
            try:
                img_bytes = self.screenshot_fn()
                return AgentReply(text="🖼️ 当前电脑桌面截图：", image_bytes=img_bytes)
            except Exception as exc:
                return AgentReply(text=f"❌ 截图失败：{exc}")

        if lower == "/new":
            session.conversation_id = None
            return AgentReply(text="✨ 已重置会话上下文，下一条消息将开启新对话。")

        if lower == "/pwd":
            return AgentReply(text=f"📁 当前工作目录：`{session.cwd}`")

        if lower.startswith("/cd "):
            target = text[4:].strip().strip('"').strip("'")
            target_path = Path(target).expanduser()
            if not target_path.is_absolute():
                target_path = (Path(session.cwd) / target_path).resolve()
            if target_path.is_dir():
                session.cwd = str(target_path)
                session.conversation_id = None
                return AgentReply(text=f"📁 已切换工作目录到：`{session.cwd}`（已开启新会话）")
            return AgentReply(text=f"❌ 目录不存在：`{target_path}`")

        if lower.startswith("/mode "):
            new_mode = text[6:].strip().lower()
            if new_mode in ("auto", "default", "accept-edits", "plan"):
                session.mode = new_mode
                return AgentReply(text=f"⚙️ 已切换 CLI 执行模式为：`{new_mode}`")
            return AgentReply(text="❌ 无效模式，可选：`auto`、`accept-edits`、`plan`、`default`")

        if lower in ("/approve", "/proceed", "同意", "确认执行", "proceed"):
            if not self.desktop_action_fn:
                return AgentReply(text="⚠️ 当前未连接桌面控制接口。")
            self.desktop_action_fn("proceed")
            return AgentReply(text="✅ 已向桌面端发送确认（Enter）。")

        if lower in ("/cancel", "/esc", "取消"):
            if not self.desktop_action_fn:
                return AgentReply(text="⚠️ 当前未连接桌面控制接口。")
            self.desktop_action_fn("cancel")
            return AgentReply(text="🛑 已向桌面端发送取消（Esc）。")

        if lower.startswith("/desktop "):
            payload = text[9:].strip()
            if not payload:
                return AgentReply(text="用法：`/desktop <要发给桌面 Antigravity 窗口的指令>`")
            if not self.desktop_send_fn:
                return AgentReply(text="⚠️ 当前未连接桌面注入接口。")
            self.desktop_send_fn(payload, True)
            return AgentReply(text=f"📤 已向桌面端 Antigravity 窗口发送：\n> {payload}")

        return self._run_agy_cli(session, text)
