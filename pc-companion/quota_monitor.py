"""
Antigravity Quota & Model Usage Monitor
Reads real-time model quotas, reset countdowns, and subscription info
from the local Antigravity language_server Connect-RPC endpoint, with
optional Antigravity CLI (agy) fallback.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _run_hidden(cmd: List[str], timeout: float = 5.0) -> str:
    """Run a subprocess without flashing a console window on Windows."""
    kwargs: Dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
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
        return proc.stdout or ""
    except Exception:
        return ""


def _parse_process_args(cmdline: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract --csrf_token and --extension_server_port from language_server args."""
    csrf_match = re.search(r"--csrf_token(?:=|\s+)([^\s\"']+)", cmdline)
    port_match = re.search(r"--extension_server_port(?:=|\s+)(\d+)", cmdline)
    csrf = csrf_match.group(1) if csrf_match else None
    ext_port = int(port_match.group(1)) if port_match else None
    return csrf, ext_port


def _find_windows_processes() -> List[Dict[str, Any]]:
    ps_script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like '*language_server*' -or $_.CommandLine -like '*csrf_token*' } | "
        "Select-Object ProcessId, Name, CommandLine | ConvertTo-Json -Compress"
    )
    out = _run_hidden(["powershell", "-NoProfile", "-Command", ps_script], timeout=6.0).strip()
    processes: List[Dict[str, Any]] = []
    if out:
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                pid = item.get("ProcessId")
                cmd = item.get("CommandLine") or ""
                if pid and "--csrf_token" in cmd:
                    processes.append({"pid": int(pid), "name": item.get("Name", ""), "cmdline": cmd})
        except Exception:
            pass

    if processes:
        return processes

    # Fallback: wmic (older Windows setups)
    wmic_out = _run_hidden(
        ["wmic", "process", "where", "name like '%language_server%'", "get", "ProcessId,CommandLine", "/FORMAT:LIST"],
        timeout=6.0,
    )
    current_cmd = ""
    current_pid: Optional[int] = None
    for line in wmic_out.splitlines():
        line = line.strip()
        if line.startswith("CommandLine="):
            current_cmd = line[len("CommandLine="):]
        elif line.startswith("ProcessId="):
            try:
                current_pid = int(line[len("ProcessId="):])
            except ValueError:
                current_pid = None
            if current_pid and "--csrf_token" in current_cmd:
                processes.append({"pid": current_pid, "name": "language_server", "cmdline": current_cmd})
            current_cmd = ""
            current_pid = None
    return processes


def _find_unix_processes() -> List[Dict[str, Any]]:
    out = _run_hidden(["ps", "-eo", "pid=,args="], timeout=4.0)
    processes: List[Dict[str, Any]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmdline = parts[1]
        if ("language_server" in cmdline or "antigravity" in cmdline) and "--csrf_token" in cmdline:
            processes.append({"pid": pid, "name": "language_server", "cmdline": cmdline})
    return processes


def _find_listening_ports_windows(pid: int) -> List[int]:
    ports: List[int] = []
    ps_script = (
        f"Get-NetTCPConnection -OwningProcess {pid} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty LocalPort"
    )
    out = _run_hidden(["powershell", "-NoProfile", "-Command", ps_script], timeout=5.0)
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            p = int(line)
            if p not in ports:
                ports.append(p)
    if ports:
        return ports

    # Fallback: netstat -ano
    net_out = _run_hidden(["netstat", "-ano", "-p", "TCP"], timeout=5.0)
    for line in net_out.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == str(pid):
            addr = parts[1]
            if ":" in addr:
                port_str = addr.rsplit(":", 1)[-1]
                if port_str.isdigit():
                    p = int(port_str)
                    if p not in ports:
                        ports.append(p)
    return ports


def _find_listening_ports_unix(pid: int) -> List[int]:
    ports: List[int] = []
    out = _run_hidden(["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"], timeout=4.0)
    for line in out.splitlines():
        m = re.search(r":(\d+)\s+\(LISTEN\)", line)
        if m:
            p = int(m.group(1))
            if p not in ports:
                ports.append(p)
    if ports:
        return ports

    ss_out = _run_hidden(["ss", "-lntp"], timeout=4.0)
    for line in ss_out.splitlines():
        if f"pid={pid}," in line:
            m = re.search(r":(\d+)\s", line)
            if m:
                p = int(m.group(1))
                if p not in ports:
                    ports.append(p)
    return ports


def _query_get_user_status(port: int, csrf_token: str, timeout: float = 2.5) -> Optional[Dict[str, Any]]:
    payload = json.dumps({
        "metadata": {
            "ideName": "antigravity",
            "extensionName": "antigravity",
            "locale": "en",
        }
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "X-Codeium-Csrf-Token": csrf_token,
    }

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for scheme in ("https", "http"):
        url = f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetUserStatus"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx if scheme == "https" else None) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    data = json.loads(raw)
                    if isinstance(data, dict) and ("userStatus" in data or "cascadeModelConfigData" in data):
                        return data
        except Exception:
            continue
    return None


def format_countdown(iso_time: Optional[str], now: Optional[datetime] = None) -> str:
    """Format an ISO-8601 reset timestamp into a concise countdown string."""
    if not iso_time:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = now or datetime.now(timezone.utc)
        diff = int((dt - ref).total_seconds())
        if diff <= 0:
            return "已重置 / 即将刷新"
        days, rem = divmod(diff, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)
    except Exception:
        return iso_time


def parse_user_status(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize GetUserStatus RPC JSON into a clean quota summary."""
    user_status = raw.get("userStatus", raw)
    plan_status = user_status.get("planStatus") or {}
    plan_info = plan_status.get("planInfo") or user_status.get("planInfo") or {}
    user_tier = user_status.get("userTier") or {}

    email = user_status.get("email") or user_status.get("name") or ""
    plan_name = (
        plan_info.get("planName")
        or user_tier.get("name")
        or plan_info.get("teamsTier")
        or "Standard"
    )

    avail_credits = plan_status.get("availablePromptCredits")
    monthly_credits = plan_info.get("monthlyPromptCredits")
    avail_flow = plan_status.get("availableFlowCredits")
    monthly_flow = plan_info.get("monthlyFlowCredits")

    cascade_data = user_status.get("cascadeModelConfigData") or {}
    client_configs = cascade_data.get("clientModelConfigs") or []

    models: List[Dict[str, Any]] = []
    seen = set()
    for cfg in client_configs:
        label = cfg.get("label") or cfg.get("modelOrAlias", {}).get("model") or "Unknown Model"
        model_id = cfg.get("modelOrAlias", {}).get("model") or label
        quota_info = cfg.get("quotaInfo") or {}
        remaining_fraction = quota_info.get("remainingFraction")
        reset_time = quota_info.get("resetTime")

        if remaining_fraction is None and not reset_time:
            continue

        dedup_key = (label, model_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        frac = float(remaining_fraction) if remaining_fraction is not None else 0.0
        frac = max(0.0, min(1.0, frac))
        remaining_pct = round(frac * 100, 1)
        used_pct = round((1.0 - frac) * 100, 1)

        models.append({
            "label": label,
            "model_id": model_id,
            "remaining_fraction": frac,
            "remaining_pct": remaining_pct,
            "used_pct": used_pct,
            "reset_time": reset_time,
            "reset_countdown": format_countdown(reset_time),
            "supports_images": bool(cfg.get("supportsImages", False)),
        })

    return {
        "available": True,
        "source": "language_server",
        "email": email,
        "plan": plan_name,
        "credits": {
            "available_prompt": avail_credits,
            "monthly_prompt": monthly_credits,
            "available_flow": avail_flow,
            "monthly_flow": monthly_flow,
        },
        "models": models,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _query_agy_cli_usage() -> Optional[Dict[str, Any]]:
    """Optional fallback using `agy -p /usage` if language_server is not running."""
    agy_bin = shutil.which("agy")
    if not agy_bin:
        return None
    out = _run_hidden([agy_bin, "-p", "/usage", "--output-format", "json"], timeout=8.0).strip()
    if not out:
        return None
    try:
        data = json.loads(out)
        return {
            "available": True,
            "source": "agy_cli",
            "raw_cli": data,
            "models": [],
            "plan": data.get("plan", "CLI"),
            "email": data.get("email", ""),
            "credits": {},
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception:
        return {
            "available": True,
            "source": "agy_cli_text",
            "raw_text": out[:1500],
            "models": [],
            "plan": "CLI",
            "email": "",
            "credits": {},
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def get_antigravity_quota(include_cli_fallback: bool = False) -> Dict[str, Any]:
    """
    Detect local Antigravity language_server and query model quotas.
    Never raises; returns structured status dict even when offline/not running.
    """
    is_win = platform.system() == "Windows"
    procs = _find_windows_processes() if is_win else _find_unix_processes()

    for proc in procs:
        pid = proc["pid"]
        csrf, ext_port = _parse_process_args(proc["cmdline"])
        if not csrf:
            continue

        ports = _find_listening_ports_windows(pid) if is_win else _find_listening_ports_unix(pid)
        if ext_port and ext_port not in ports:
            ports.append(ext_port)

        for port in ports:
            raw = _query_get_user_status(port, csrf)
            if raw:
                parsed = parse_user_status(raw)
                parsed["pid"] = pid
                parsed["port"] = port
                return parsed

    if include_cli_fallback:
        cli_res = _query_agy_cli_usage()
        if cli_res:
            return cli_res

    return {
        "available": False,
        "source": "none",
        "error": "未检测到运行中的 Antigravity 本地服务 (language_server)。请确认桌面端 Antigravity 已打开并登录。",
        "models": [],
        "plan": "",
        "email": "",
        "credits": {},
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _progress_bar(remaining_pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round((remaining_pct / 100.0) * width)))
    return "█" * filled + "░" * (width - filled)


def format_quota_report(data: Dict[str, Any]) -> str:
    """Render quota dict into a readable chat message for Telegram/Feishu/QQ."""
    if not data.get("available"):
        return f"⚠️ 无法获取模型用量：\n{data.get('error', '未知错误')}"

    if data.get("source") == "agy_cli_text":
        return f"📊 Antigravity CLI 用量：\n{data.get('raw_text', '')}"

    lines = ["📊 **Antigravity 模型用量与额度**"]
    if data.get("plan") or data.get("email"):
        meta = " | ".join(x for x in [data.get("plan"), data.get("email")] if x)
        lines.append(f"👤 账户：{meta}")

    credits = data.get("credits") or {}
    if credits.get("available_prompt") is not None:
        total = credits.get("monthly_prompt")
        avail = credits.get("available_prompt")
        lines.append(f"💎 Prompt Credits：{avail}" + (f" / {total}" if total is not None else ""))

    models = data.get("models") or []
    if not models:
        lines.append("暂无模型配额明细（可能是刚启动尚未加载完成）。")
    else:
        lines.append("")
        for m in models:
            rem = m["remaining_pct"]
            bar = _progress_bar(rem)
            icon = "🟢" if rem >= 50 else ("🟡" if rem >= 20 else "🔴")
            lines.append(f"{icon} **{m['label']}**")
            lines.append(f"   `{bar}` 剩余 **{rem:.0f}%** (重置: {m['reset_countdown']})")

    lines.append(f"\n🕒 更新时间：{data.get('checked_at', '')}")
    return "\n".join(lines)
