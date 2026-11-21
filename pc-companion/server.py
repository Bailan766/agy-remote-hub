"""
Antigravity Pocket (AGY Remote Hub) - PC Companion & LAN Bridge Server
Provides REST API, Web Remote Control, Live Screen Mirror, and APK distribution.
"""

import os
import sys
import glob
import json
import time
import socket
import ctypes
import secrets
import io
import asyncio
from copy import deepcopy
from typing import Optional, List, Dict, Any
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import qrcode
import pyperclip
import mss

try:
    from pynput.mouse import Controller as MouseController, Button as MouseButton
    from pynput.keyboard import Controller as KeyboardController, Key
except Exception:
    MouseController = None
    MouseButton = None
    KeyboardController = None
    Key = None

from quota_monitor import get_antigravity_quota
from agent_runner import AgentRunner
from im_bridge import IMBridgeManager

# Windows API for window management & Keep-Awake
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def set_keep_awake(enabled: bool = True):
    """Prevent Windows from going to sleep while remote control is active."""
    try:
        flags = ES_CONTINUOUS
        if enabled:
            flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return True
    except Exception as e:
        print(f"Error setting keep awake: {e}")
        return False

# Directories
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DIST_DIR = BASE_DIR / "dist"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
DIST_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_BRAIN_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".gemini" / "antigravity" / "brain"
CONFIG_FILE = BASE_DIR / "config.json"


def _default_config() -> dict:
    return {
        "token": secrets.token_urlsafe(16),
        "port": 8765,
        "keep_awake": True,
        "workspace_dir": str(Path.home()),
        "agy_mode": "auto",
        "agy_model": "",
        "agy_path": "",
        "custom_shortcuts": [
            {"id": "plan", "label": "📐 /plan", "text": "/plan "},
            {"id": "goal", "label": "🎯 /goal", "text": "/goal "},
            {"id": "compact", "label": "📦 /compact", "text": "/compact"},
            {"id": "boost", "label": "⚡ /boost", "text": "/boost "},
            {"id": "proceed", "label": "✅ Proceed / 同意", "text": "Proceed"},
            {"id": "yes", "label": "👍 确认执行", "text": "好，开始执行"}
        ],
        "im_bridge": {
            "enabled": False,
            "fallback_to_desktop": True,
            "telegram": {
                "enabled": False,
                "bot_token": "",
                "proxy_url": "",
                "allowed_user_ids": []
            },
            "feishu": {
                "enabled": False,
                "app_id": "",
                "app_secret": "",
                "allowed_open_ids": []
            },
            "qq": {
                "enabled": False,
                "ws_url": "ws://127.0.0.1:3001",
                "access_token": "",
                "allowed_qq": []
            }
        }
    }


def _merge_defaults(target: dict, defaults: dict) -> dict:
    merged = deepcopy(defaults)
    for k, v in target.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _merge_defaults(v, merged[k])
        else:
            merged[k] = v
    return merged


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_or_create_config() -> dict:
    defaults = _default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            merged = _merge_defaults(loaded, defaults)
            if merged != loaded:
                save_config(merged)
            return merged
        except Exception:
            pass
    save_config(defaults)
    return defaults

CONFIG = get_or_create_config()
AUTH_TOKEN = CONFIG.get("token", "agypocket_default")

def get_lan_ip() -> str:
    """Find the best local LAN IPv4 address (prefer 192.168.x.x or 10.x.x.x)."""
    candidates = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith("127."):
                continue
            if ip.startswith("172.19.") or ip.startswith("172.18."):
                # Often VPN/TUN virtual adapters
                candidates.append((3, ip))
            elif ip.startswith("192.168."):
                candidates.append((1, ip))
            elif ip.startswith("10."):
                candidates.append((2, ip))
            else:
                candidates.append((4, ip))
    except Exception:
        pass
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return "127.0.0.1"

# Fast Window Focus via win32 ctypes
def find_and_focus_antigravity_window() -> bool:
    try:
        user32 = ctypes.windll.user32
        target_hwnd = [0]
        
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        
        def callback(hwnd, extra):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if "Antigravity" in title or "Gemini" in title:
                        target_hwnd[0] = hwnd
                        return False
            return True
            
        user32.EnumWindows(EnumWindowsProc(callback), 0)
        
        hwnd = target_hwnd[0]
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            return True
    except Exception as e:
        print(f"Window focus error: {e}")
    return False

# Input controllers
mouse = MouseController() if MouseController else None
keyboard = KeyboardController() if KeyboardController else None

app = FastAPI(title="Antigravity Pocket Hub", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_token(request: Request, token: Optional[str] = Query(None)):
    header_token = request.headers.get("X-Auth-Token")
    query_token = token
    if header_token == AUTH_TOKEN or query_token == AUTH_TOKEN:
        return True
    # If no token passed, reject unauthorized
    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")

# Models
class PromptRequest(BaseModel):
    text: str
    auto_submit: bool = True

class ChatRequest(BaseModel):
    text: str
    chat_key: str = "web:mobile"

class QuickActionRequest(BaseModel):
    action: str
    param: Optional[str] = None

class TapRequest(BaseModel):
    x: float  # Normalized 0.0 - 1.0
    y: float  # Normalized 0.0 - 1.0

class IMBridgeConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    fallback_to_desktop: Optional[bool] = None
    workspace_dir: Optional[str] = None
    agy_mode: Optional[str] = None
    agy_model: Optional[str] = None
    telegram: Optional[Dict[str, Any]] = None
    feishu: Optional[Dict[str, Any]] = None
    qq: Optional[Dict[str, Any]] = None

class ModelSelectRequest(BaseModel):
    model: str = ""
    chat_key: Optional[str] = None


# ----------------- Core Helpers -----------------

def collect_conversations_summary() -> List[Dict[str, Any]]:
    if not DEFAULT_BRAIN_DIR.exists():
        return []
    results = []
    conv_dirs = [d for d in DEFAULT_BRAIN_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
    conv_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)

    for cdir in conv_dirs[:15]:
        conv_id = cdir.name
        transcript_path = cdir / ".system_generated" / "logs" / "transcript.jsonl"
        last_user_msg = ""
        last_step_status = "UNKNOWN"
        last_time = cdir.stat().st_mtime

        if transcript_path.exists():
            try:
                with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [line.strip() for line in f if line.strip()]
                for line in reversed(lines):
                    try:
                        data = json.loads(line)
                        if not last_user_msg and data.get("type") == "USER_INPUT":
                            last_user_msg = data.get("content", "")
                        if last_step_status == "UNKNOWN" and "status" in data:
                            last_step_status = data.get("status")
                        if last_user_msg and last_step_status != "UNKNOWN":
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        artifacts = [f.name for f in cdir.glob("*.md")]
        results.append({
            "id": conv_id,
            "title": (last_user_msg[:60] + "...") if len(last_user_msg) > 60 else (last_user_msg or conv_id),
            "status": last_step_status,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_time)),
            "artifact_count": len(artifacts),
            "artifacts": artifacts
        })
    return results


def inject_prompt_to_desktop(text: str, auto_submit: bool = True) -> Dict[str, Any]:
    if not keyboard or not Key:
        raise RuntimeError("Desktop keyboard controller is unavailable in this environment.")
    find_and_focus_antigravity_window()
    time.sleep(0.15)
    pyperclip.copy(text)
    with keyboard.pressed(Key.ctrl):
        keyboard.press('v')
        keyboard.release('v')
    if auto_submit:
        time.sleep(0.1)
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
    return {"status": "success", "sent": text}


def trigger_quick_action(action: str, param: Optional[str] = None) -> Dict[str, Any]:
    act = action.lower()
    if act == "keep_awake":
        enabled = param.lower() in ("true", "1") if param else True
        success = set_keep_awake(enabled)
        return {"status": "ok", "keep_awake": enabled, "success": success}

    if not keyboard or not Key:
        raise RuntimeError("Desktop keyboard controller is unavailable in this environment.")

    find_and_focus_antigravity_window()
    time.sleep(0.1)

    if act == "plan":
        pyperclip.copy("/plan ")
        with keyboard.pressed(Key.ctrl):
            keyboard.press('v')
            keyboard.release('v')
    elif act == "goal":
        pyperclip.copy("/goal ")
        with keyboard.pressed(Key.ctrl):
            keyboard.press('v')
            keyboard.release('v')
    elif act == "compact":
        pyperclip.copy("/compact")
        with keyboard.pressed(Key.ctrl):
            keyboard.press('v')
            keyboard.release('v')
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
    elif act == "boost":
        pyperclip.copy("/boost ")
        with keyboard.pressed(Key.ctrl):
            keyboard.press('v')
            keyboard.release('v')
    elif act in ("proceed", "approve", "enter"):
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
    elif act in ("cancel", "esc"):
        keyboard.press(Key.esc)
        keyboard.release(Key.esc)

    return {"status": "ok", "action": act}


def capture_screenshot_bytes() -> bytes:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        from PIL import Image
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return buf.getvalue()


agent_runner = AgentRunner(
    config_getter=lambda: CONFIG,
    screenshot_fn=capture_screenshot_bytes,
    desktop_send_fn=inject_prompt_to_desktop,
    desktop_action_fn=trigger_quick_action,
    conversations_fn=collect_conversations_summary,
    config_saver=save_config,
)
im_bridge = IMBridgeManager(config_getter=lambda: CONFIG, runner=agent_runner)


# ----------------- Routes -----------------

@app.get("/", response_class=HTMLResponse)
async def serve_index(token: Optional[str] = Query(None)):
    """Serves the mobile web interface."""
    index_file = STATIC_DIR / "mobile_ui.html"
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse("<h2>Antigravity Pocket Mobile UI loading...</h2>")

@app.get("/api/info")
async def get_system_info(token: bool = Depends(verify_token)):
    lan_ip = get_lan_ip()
    port = CONFIG.get("port", 8765)
    return {
        "status": "online",
        "hostname": socket.gethostname(),
        "lan_ip": lan_ip,
        "port": port,
        "token": AUTH_TOKEN,
        "hub_url": f"http://{lan_ip}:{port}/?token={AUTH_TOKEN}",
        "official_url": "https://antigravity.google",
        "apk_available": (DIST_DIR / "agy-pocket.apk").exists(),
        "shortcuts": CONFIG.get("custom_shortcuts", []),
        "im_bridge": im_bridge.status(),
        "current_model": CONFIG.get("agy_model", ""),
    }

@app.get("/api/quota")
async def get_quota(include_cli: bool = Query(False), token: bool = Depends(verify_token)):
    """Query local Antigravity model quotas, reset countdowns, and prompt credits."""
    data = await asyncio.to_thread(get_antigravity_quota, include_cli)
    data["current_model"] = CONFIG.get("agy_model", "")
    return data

@app.post("/api/model")
async def select_model(req: ModelSelectRequest, token: bool = Depends(verify_token)):
    """Switch active/default Antigravity CLI model across sessions."""
    model_val = "" if req.model.strip().lower() in ("default", "reset", "auto", "系统默认") else req.model.strip()
    agent_runner.set_default_model(model_val, req.chat_key)
    return {"status": "ok", "current_model": CONFIG.get("agy_model", "")}

@app.get("/api/im/status")
async def get_im_status(token: bool = Depends(verify_token)):
    """Return IM bridge runtime status and sanitized config."""
    im_cfg = CONFIG.get("im_bridge") or {}
    tg = im_cfg.get("telegram") or {}
    fs = im_cfg.get("feishu") or {}
    qq = im_cfg.get("qq") or {}
    return {
        "runtime": im_bridge.status(),
        "config": {
            "enabled": bool(im_cfg.get("enabled", False)),
            "fallback_to_desktop": bool(im_cfg.get("fallback_to_desktop", True)),
            "workspace_dir": CONFIG.get("workspace_dir", ""),
            "agy_mode": CONFIG.get("agy_mode", "auto"),
            "agy_model": CONFIG.get("agy_model", ""),
            "telegram": {
                "enabled": bool(tg.get("enabled", False)),
                "has_token": bool(tg.get("bot_token")),
                "proxy_url": tg.get("proxy_url", ""),
                "allowed_user_ids": tg.get("allowed_user_ids", []),
            },
            "feishu": {
                "enabled": bool(fs.get("enabled", False)),
                "app_id": fs.get("app_id", ""),
                "has_secret": bool(fs.get("app_secret")),
                "allowed_open_ids": fs.get("allowed_open_ids", []),
            },
            "qq": {
                "enabled": bool(qq.get("enabled", False)),
                "ws_url": qq.get("ws_url", ""),
                "has_token": bool(qq.get("access_token")),
                "allowed_qq": qq.get("allowed_qq", []),
            },
        },
    }

@app.post("/api/im/config")
async def update_im_config(req: IMBridgeConfigRequest, token: bool = Depends(verify_token)):
    """Update IM bridge settings in config.json and reload active workers."""
    im_cfg = CONFIG.setdefault("im_bridge", {})
    if req.enabled is not None:
        im_cfg["enabled"] = req.enabled
    if req.fallback_to_desktop is not None:
        im_cfg["fallback_to_desktop"] = req.fallback_to_desktop
    if req.workspace_dir is not None and req.workspace_dir.strip():
        CONFIG["workspace_dir"] = req.workspace_dir.strip()
    if req.agy_mode is not None and req.agy_mode in ("auto", "default", "accept-edits", "plan"):
        CONFIG["agy_mode"] = req.agy_mode
    if req.agy_model is not None:
        agent_runner.set_default_model(req.agy_model)

    for channel in ("telegram", "feishu", "qq"):
        patch = getattr(req, channel)
        if isinstance(patch, dict):
            target = im_cfg.setdefault(channel, {})
            for k, v in patch.items():
                target[k] = v

    save_config(CONFIG)
    im_bridge.reload()
    return {"status": "ok", "runtime": im_bridge.status()}

@app.post("/api/chat")
async def chat_with_agent(req: ChatRequest, token: bool = Depends(verify_token)):
    """Conversational endpoint shared with IM bridge (supports /usage, /status, CLI prompts)."""
    reply = await asyncio.to_thread(agent_runner.handle_message, req.chat_key, req.text)
    return {
        "status": "ok",
        "text": reply.text,
        "has_image": reply.image_bytes is not None,
    }

@app.get("/api/qrcode")
async def generate_qr(text: str = Query(...)):
    """Generate dynamic QR code PNG."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")

@app.get("/api/conversations")
async def list_conversations(token: bool = Depends(verify_token)):
    """List recent Antigravity conversations and their execution state."""
    return {"conversations": collect_conversations_summary()}

@app.get("/api/conversations/{conv_id}")
async def get_conversation_detail(conv_id: str, token: bool = Depends(verify_token)):
    """Get conversation steps and artifacts."""
    cdir = DEFAULT_BRAIN_DIR / conv_id
    if not cdir.exists():
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    transcript_path = cdir / ".system_generated" / "logs" / "transcript.jsonl"
    steps = []
    if transcript_path.exists():
        try:
            with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            item = json.loads(line)
                            steps.append({
                                "step_index": item.get("step_index"),
                                "type": item.get("type"),
                                "source": item.get("source"),
                                "status": item.get("status"),
                                "content": item.get("content", ""),
                                "created_at": item.get("created_at")
                            })
                        except Exception:
                            continue
        except Exception as e:
            print(f"Error reading transcript: {e}")
            
    artifacts = []
    for md_file in cdir.glob("*.md"):
        try:
            artifacts.append({
                "filename": md_file.name,
                "size": md_file.stat().st_size,
                "content": md_file.read_text(encoding="utf-8", errors="ignore")
            })
        except Exception:
            pass
            
    return {
        "id": conv_id,
        "steps": steps[-25:],  # Return latest 25 steps for responsiveness
        "artifacts": artifacts
    }

@app.post("/api/send_prompt")
async def send_prompt(req: PromptRequest, token: bool = Depends(verify_token)):
    """Focus Antigravity and inject prompt text."""
    try:
        return inject_prompt_to_desktop(req.text, req.auto_submit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quick_action")
async def quick_action(req: QuickActionRequest, token: bool = Depends(verify_token)):
    """Trigger predefined quick action (slash commands, approve, keep-awake, etc.)."""
    try:
        return trigger_quick_action(req.action, req.param)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/screen/shot.jpg")
async def get_screen_shot(token: bool = Depends(verify_token)):
    """Capture screen frame and return JPEG."""
    try:
        return Response(content=capture_screenshot_bytes(), media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/screen/tap")
async def tap_screen(req: TapRequest, token: bool = Depends(verify_token)):
    """Map normalized touch point (0.0 - 1.0) to screen pixel and click."""
    if not mouse or not MouseButton:
        raise HTTPException(status_code=500, detail="Desktop mouse controller is unavailable.")
    try:
        with mss.mss() as sct:
            mon = sct.monitors[1]
            target_x = int(mon["left"] + req.x * mon["width"])
            target_y = int(mon["top"] + req.y * mon["height"])
            
            mouse.position = (target_x, target_y)
            time.sleep(0.05)
            mouse.click(MouseButton.left, 1)
            return {"status": "ok", "clicked": (target_x, target_y)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/agy-pocket.apk")
async def download_apk():
    """Serves the built Android APK for mobile devices."""
    apk_path = DIST_DIR / "agy-pocket.apk"
    if not apk_path.exists():
        # Fallback check inside android-app build outputs
        gradle_apk = BASE_DIR.parent / "android-app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        if gradle_apk.exists():
            import shutil
            shutil.copy2(gradle_apk, apk_path)
            
    if apk_path.exists():
        return FileResponse(
            apk_path,
            media_type="application/vnd.android.package-archive",
            filename="AntigravityPocket.apk"
        )
    raise HTTPException(status_code=404, detail="APK has not been built yet. Please compile the Android project first.")

if __name__ == "__main__":
    port = CONFIG.get("port", 8765)
    lan_ip = get_lan_ip()
    print("=" * 60)
    print("🚀 Antigravity Pocket LAN Bridge Server Running")
    print(f"👉 Local Access:   http://127.0.0.1:{port}/?token={AUTH_TOKEN}")
    print(f"📱 Mobile Access:  http://{lan_ip}:{port}/?token={AUTH_TOKEN}")
    print(f"📦 APK Download:   http://{lan_ip}:{port}/download/agy-pocket.apk")
    print("=" * 60)
    
    if CONFIG.get("keep_awake", True):
        set_keep_awake(True)
        print("💡 Keep-Awake enabled (preventing PC sleep)")

    im_bridge.start()
    print(f"🤖 IM Bridge status: {im_bridge.status()}")
        
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
