"""
Self-test script for Antigravity Pocket PC Companion
Verifies API endpoints, quota parser, conversational agent runner, and IM bridge status.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add current dir to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from server import app, CONFIG, AUTH_TOKEN, get_lan_ip, DEFAULT_BRAIN_DIR, agent_runner
from quota_monitor import parse_user_status, format_quota_report, format_countdown
from fastapi.testclient import TestClient


def run_tests():
    print("1. Testing LAN IP detection...")
    lan_ip = get_lan_ip()
    print(f"   Detected LAN IP: {lan_ip}")
    assert lan_ip, "LAN IP should not be empty"

    print("2. Testing Brain directory...")
    print(f"   Brain path: {DEFAULT_BRAIN_DIR} (exists={DEFAULT_BRAIN_DIR.exists()})")

    print("3. Testing Quota parser & formatter...")
    future_iso = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=15)).isoformat()
    sample_rpc = {
        "userStatus": {
            "email": "dev@example.com",
            "planStatus": {
                "availablePromptCredits": 420,
                "planInfo": {
                    "planName": "Google AI Pro",
                    "monthlyPromptCredits": 500,
                },
            },
            "cascadeModelConfigData": {
                "clientModelConfigs": [
                    {
                        "label": "Gemini 4 Neon",
                        "modelOrAlias": {"model": "gemini-4-neon"},
                        "quotaInfo": {"remainingFraction": 0.75, "resetTime": future_iso},
                        "supportsImages": True,
                    },
                    {
                        "label": "Gemini 4 Hydrogen",
                        "modelOrAlias": {"model": "gemini-4-hydrogen"},
                        "quotaInfo": {"remainingFraction": 0.15, "resetTime": future_iso},
                    },
                ]
            },
        }
    }
    parsed = parse_user_status(sample_rpc)
    assert parsed["available"] is True
    assert parsed["plan"] == "Google AI Pro"
    assert len(parsed["models"]) == 2
    assert parsed["models"][0]["remaining_pct"] == 75.0
    assert parsed["models"][1]["used_pct"] == 85.0
    report = format_quota_report(parsed)
    assert "Gemini 4 Neon" in report and "75%" in report
    assert format_countdown(future_iso) != "-"
    print("   Quota parser & formatter passed.")

    print("4. Testing AgentRunner commands & model switching...")
    help_reply = agent_runner.handle_message("test:1", "/help")
    assert "/usage" in help_reply.text and "/screen" in help_reply.text and "/model" in help_reply.text
    pwd_reply = agent_runner.handle_message("test:1", "/pwd")
    assert "当前工作目录" in pwd_reply.text
    mode_reply = agent_runner.handle_message("test:1", "/mode plan")
    assert "plan" in mode_reply.text
    model_reply = agent_runner.handle_message("test:1", "/model gemini-4-neon")
    assert "gemini-4-neon" in model_reply.text
    reset_model_reply = agent_runner.handle_message("test:1", "/model default")
    assert "默认模型" in reset_model_reply.text
    new_reply = agent_runner.handle_message("test:1", "/new")
    assert "新对话" in new_reply.text
    print("   AgentRunner commands passed.")

    print("5. Testing FastAPI endpoints with TestClient...")
    client = TestClient(app)

    # Info without token -> 401
    resp = client.get("/api/info")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    # Info with token -> 200
    resp = client.get(f"/api/info?token={AUTH_TOKEN}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    info = resp.json()
    print(f"   Info response: {info['hostname']} | status: {info['status']}")
    assert "im_bridge" in info and "current_model" in info

    # Model switch endpoint
    resp = client.post(f"/api/model?token={AUTH_TOKEN}", json={"model": "gemini-4-neon"})
    assert resp.status_code == 200 and resp.json()["current_model"] == "gemini-4-neon"
    resp = client.post(f"/api/model?token={AUTH_TOKEN}", json={"model": "default"})
    assert resp.status_code == 200 and resp.json()["current_model"] == ""
    print("   Model switch endpoint OK.")

    # Conversations list
    resp = client.get(f"/api/conversations?token={AUTH_TOKEN}")
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    assert isinstance(convs, list)
    print(f"   Found {len(convs)} conversations in brain.")

    # Quota endpoint
    resp = client.get(f"/api/quota?token={AUTH_TOKEN}")
    assert resp.status_code == 200
    quota_data = resp.json()
    assert "available" in quota_data and "models" in quota_data and "current_model" in quota_data
    print(f"   Quota endpoint OK (available={quota_data['available']}).")

    # IM status endpoint
    resp = client.get(f"/api/im/status?token={AUTH_TOKEN}")
    assert resp.status_code == 200
    im_data = resp.json()
    assert "runtime" in im_data and "config" in im_data and "agy_model" in im_data["config"]
    print("   IM status endpoint OK.")

    # Chat endpoint
    resp = client.post(
        f"/api/chat?token={AUTH_TOKEN}",
        json={"text": "/status", "chat_key": "test:web"},
    )
    assert resp.status_code == 200
    assert "主机名" in resp.json()["text"]
    print("   Chat endpoint OK.")

    # QR Code generator
    resp = client.get("/api/qrcode?text=https://antigravity.google")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    print(f"   QR Code generated: {len(resp.content)} bytes PNG")

    # Mobile Web UI
    resp = client.get(f"/?token={AUTH_TOKEN}")
    assert resp.status_code == 200
    assert "AGY Pocket" in resp.text and "view-quota" in resp.text
    print("   Mobile HTML served successfully.")

    print("\n[SUCCESS] All PC Companion self-tests passed successfully!")


if __name__ == "__main__":
    run_tests()
