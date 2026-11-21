"""
Multi-Channel IM Bridge (Telegram / Feishu WebSocket / QQ OneBot v11)
Runs in background threads inside server.py / launcher_gui.py or standalone,
allowing OpenClaw-style conversational control & quota queries from mobile IM apps
without exposing any public IP or router port.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

from agent_runner import AgentReply, AgentRunner


def _split_chunks(text: str, max_len: int = 3800) -> List[str]:
    if len(text) <= max_len:
        return [text]
    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= max_len // 3:
            cut = max_len
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


class TelegramWorker:
    def __init__(self, cfg: Dict[str, Any], runner: AgentRunner):
        self.cfg = cfg
        self.runner = runner
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state: str = "stopped"
        self.last_error: str = ""

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_thread, daemon=True, name="TelegramBridge")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)
        self.state = "stopped"

    def _run_thread(self):
        try:
            asyncio.run(self._loop())
        except Exception as exc:
            self.last_error = str(exc)
            self.state = "error"

    async def _loop(self):
        try:
            import httpx
        except ImportError:
            self.last_error = "缺少 httpx 依赖，请运行 pip install -r requirements.txt"
            self.state = "error"
            return

        token = (self.cfg.get("bot_token") or "").strip()
        if not token:
            self.last_error = "未配置 Telegram bot_token"
            self.state = "error"
            return

        allowed = {str(x).strip() for x in (self.cfg.get("allowed_user_ids") or []) if str(x).strip()}
        proxy = (self.cfg.get("proxy_url") or "").strip() or None
        base_url = f"https://api.telegram.org/bot{token}"

        offset = 0
        self.state = "running"
        self.last_error = ""

        client_kwargs: Dict[str, Any] = {"timeout": 35.0}
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            while not self.stop_event.is_set():
                try:
                    resp = await client.get(
                        f"{base_url}/getUpdates",
                        params={"offset": offset, "timeout": 25, "allowed_updates": ["message"]},
                    )
                    data = resp.json()
                    if not data.get("ok"):
                        self.last_error = str(data.get("description") or "Telegram API error")
                        await asyncio.sleep(4)
                        continue

                    self.last_error = ""
                    for upd in data.get("result", []):
                        offset = max(offset, upd["update_id"] + 1)
                        msg = upd.get("message") or {}
                        text = (msg.get("text") or "").strip()
                        if not text:
                            continue
                        chat_id = str(msg["chat"]["id"])
                        user_id = str((msg.get("from") or {}).get("id") or chat_id)

                        if allowed and user_id not in allowed and chat_id not in allowed:
                            await client.post(
                                f"{base_url}/sendMessage",
                                json={
                                    "chat_id": chat_id,
                                    "text": f"⛔ 未授权用户 (ID: {user_id})。请在 pc-companion 配置中加入白名单。",
                                },
                            )
                            continue

                        await client.post(f"{base_url}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
                        reply = await asyncio.to_thread(self.runner.handle_message, f"tg:{chat_id}", text)
                        await self._send_reply(client, base_url, chat_id, reply)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    self.last_error = str(exc)
                    await asyncio.sleep(4)

    async def _send_reply(self, client: Any, base_url: str, chat_id: str, reply: AgentReply):
        if reply.image_bytes:
            files = {"photo": (reply.image_name, reply.image_bytes, "image/jpeg")}
            await client.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": chat_id, "caption": (reply.text or "")[:900]},
                files=files,
            )
            return

        for chunk in _split_chunks(reply.text or "✅ 完成"):
            await client.post(
                f"{base_url}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
            )


class FeishuWorker:
    def __init__(self, cfg: Dict[str, Any], runner: AgentRunner):
        self.cfg = cfg
        self.runner = runner
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state: str = "stopped"
        self.last_error: str = ""

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_thread, daemon=True, name="FeishuBridge")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.state = "stopped"

    def _run_thread(self):
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateImageRequest,
                CreateImageRequestBody,
                CreateMessageRequest,
                CreateMessageRequestBody,
            )
        except ImportError:
            self.last_error = "未安装 lark-oapi，请运行: pip install lark-oapi"
            self.state = "error"
            return

        app_id = (self.cfg.get("app_id") or "").strip()
        app_secret = (self.cfg.get("app_secret") or "").strip()
        if not app_id or not app_secret:
            self.last_error = "未配置飞书 app_id 或 app_secret"
            self.state = "error"
            return

        allowed = {str(x).strip() for x in (self.cfg.get("allowed_open_ids") or []) if str(x).strip()}
        api_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

        def send_text(chat_id: str, text: str):
            for chunk in _split_chunks(text, max_len=3500):
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .msg_type("text")
                        .content(json.dumps({"text": chunk}, ensure_ascii=False))
                        .build()
                    )
                    .build()
                )
                api_client.im.v1.message.create(req)

        def send_reply(chat_id: str, reply: AgentReply):
            if reply.image_bytes:
                try:
                    import io

                    img_req = (
                        CreateImageRequest.builder()
                        .request_body(
                            CreateImageRequestBody.builder()
                            .image_type("message")
                            .image(io.BytesIO(reply.image_bytes))
                            .build()
                        )
                        .build()
                    )
                    img_resp = api_client.im.v1.image.create(img_req)
                    if img_resp.success() and img_resp.data and img_resp.data.image_key:
                        msg_req = (
                            CreateMessageRequest.builder()
                            .receive_id_type("chat_id")
                            .request_body(
                                CreateMessageRequestBody.builder()
                                .receive_id(chat_id)
                                .msg_type("image")
                                .content(json.dumps({"image_key": img_resp.data.image_key}))
                                .build()
                            )
                            .build()
                        )
                        api_client.im.v1.message.create(msg_req)
                        return
                except Exception:
                    pass
            send_text(chat_id, reply.text or "✅ 完成")

        def on_message(data: Any):
            try:
                event = data.event
                msg = event.message
                if msg.message_type != "text":
                    return
                sender_id = ""
                if event.sender and event.sender.sender_id:
                    sender_id = event.sender.sender_id.open_id or ""
                chat_id = msg.chat_id

                if allowed and sender_id not in allowed:
                    send_text(chat_id, f"⛔ 未授权飞书账号 (open_id: {sender_id})。")
                    return

                content_obj = json.loads(msg.content or "{}")
                text = (content_obj.get("text") or "").strip()
                if not text:
                    return

                def worker():
                    reply = self.runner.handle_message(f"feishu:{chat_id}", text)
                    send_reply(chat_id, reply)

                threading.Thread(target=worker, daemon=True).start()
            except Exception as exc:
                self.last_error = str(exc)

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .build()
        )

        self.state = "running"
        self.last_error = ""
        try:
            ws_client = lark.ws.Client(app_id, app_secret, event_handler=event_handler, log_level=lark.LogLevel.WARNING)
            ws_client.start()
        except Exception as exc:
            self.last_error = str(exc)
            self.state = "error"


class QQOneBotWorker:
    """Connects as a client to an OneBot v11 forward WebSocket (NapCat / Lagrange / LLOneBot)."""

    def __init__(self, cfg: Dict[str, Any], runner: AgentRunner):
        self.cfg = cfg
        self.runner = runner
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state: str = "stopped"
        self.last_error: str = ""

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_thread, daemon=True, name="QQOneBotBridge")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)
        self.state = "stopped"

    def _run_thread(self):
        try:
            asyncio.run(self._loop())
        except Exception as exc:
            self.last_error = str(exc)
            self.state = "error"

    async def _loop(self):
        try:
            import websockets
        except ImportError:
            self.last_error = "缺少 websockets 依赖，请运行 pip install -r requirements.txt"
            self.state = "error"
            return

        ws_url = (self.cfg.get("ws_url") or "").strip()
        if not ws_url:
            self.last_error = "未配置 QQ OneBot ws_url (例如 ws://127.0.0.1:3001)"
            self.state = "error"
            return

        access_token = (self.cfg.get("access_token") or "").strip()
        allowed = {str(x).strip() for x in (self.cfg.get("allowed_qq") or []) if str(x).strip()}
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else None

        if access_token and "access_token=" not in ws_url:
            sep = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{sep}access_token={urllib.parse.quote(access_token)}"

        while not self.stop_event.is_set():
            try:
                async with websockets.connect(ws_url, additional_headers=headers) as ws:
                    self.state = "running"
                    self.last_error = ""
                    while not self.stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        except asyncio.TimeoutError:
                            continue

                        evt = json.loads(raw)
                        if evt.get("post_type") != "message" or evt.get("message_type") != "private":
                            continue

                        user_id = str(evt.get("user_id") or "")
                        raw_msg = (evt.get("raw_message") or "").strip()
                        if not raw_msg:
                            continue

                        if allowed and user_id not in allowed:
                            await self._send_private(ws, int(user_id), f"⛔ 未授权 QQ 号 ({user_id})。")
                            continue

                        reply = await asyncio.to_thread(self.runner.handle_message, f"qq:{user_id}", raw_msg)
                        if reply.image_bytes:
                            b64 = base64.b64encode(reply.image_bytes).decode("ascii")
                            cq = f"{reply.text}\n[CQ:image,file=base64://{b64}]"
                            await self._send_private(ws, int(user_id), cq)
                        else:
                            for chunk in _split_chunks(reply.text or "✅ 完成", max_len=2500):
                                await self._send_private(ws, int(user_id), chunk)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.last_error = str(exc)
                self.state = "reconnecting"
                await asyncio.sleep(5)

    async def _send_private(self, ws: Any, user_id: int, message: str):
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": user_id, "message": message},
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))


class IMBridgeManager:
    def __init__(self, config_getter: Callable[[], Dict[str, Any]], runner: AgentRunner):
        self.get_config = config_getter
        self.runner = runner
        self.telegram: Optional[TelegramWorker] = None
        self.feishu: Optional[FeishuWorker] = None
        self.qq: Optional[QQOneBotWorker] = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            cfg = self.get_config()
            im_cfg = cfg.get("im_bridge") or {}
            if not im_cfg.get("enabled"):
                self._stop_all_locked()
                return

            tg_cfg = im_cfg.get("telegram") or {}
            if tg_cfg.get("enabled") and tg_cfg.get("bot_token"):
                self.telegram = TelegramWorker(tg_cfg, self.runner)
                self.telegram.start()

            fs_cfg = im_cfg.get("feishu") or {}
            if fs_cfg.get("enabled") and fs_cfg.get("app_id") and fs_cfg.get("app_secret"):
                self.feishu = FeishuWorker(fs_cfg, self.runner)
                self.feishu.start()

            qq_cfg = im_cfg.get("qq") or {}
            if qq_cfg.get("enabled") and qq_cfg.get("ws_url"):
                self.qq = QQOneBotWorker(qq_cfg, self.runner)
                self.qq.start()

    def stop(self):
        with self._lock:
            self._stop_all_locked()

    def _stop_all_locked(self):
        for w in (self.telegram, self.feishu, self.qq):
            if w:
                try:
                    w.stop()
                except Exception:
                    pass
        self.telegram = None
        self.feishu = None
        self.qq = None

    def reload(self):
        self.stop()
        self.start()

    def status(self) -> Dict[str, Any]:
        cfg = (self.get_config().get("im_bridge") or {})
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "telegram": {
                "enabled": bool((cfg.get("telegram") or {}).get("enabled", False)),
                "state": self.telegram.state if self.telegram else "stopped",
                "error": self.telegram.last_error if self.telegram else "",
            },
            "feishu": {
                "enabled": bool((cfg.get("feishu") or {}).get("enabled", False)),
                "state": self.feishu.state if self.feishu else "stopped",
                "error": self.feishu.last_error if self.feishu else "",
            },
            "qq": {
                "enabled": bool((cfg.get("qq") or {}).get("enabled", False)),
                "state": self.qq.state if self.qq else "stopped",
                "error": self.qq.last_error if self.qq else "",
            },
        }


if __name__ == "__main__":
    from server import CONFIG, agent_runner, im_bridge

    print("Starting standalone IM Bridge...", CONFIG.get("im_bridge"))
    im_bridge.start()
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        im_bridge.stop()
