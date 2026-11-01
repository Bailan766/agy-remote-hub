"""
Self-test script for Antigravity Pocket PC Companion
Verifies API endpoints, Antigravity brain discovery, and QR generation.
"""

import sys
import json
from pathlib import Path

# Add current dir to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from server import app, CONFIG, AUTH_TOKEN, get_lan_ip, set_keep_awake, DEFAULT_BRAIN_DIR
from fastapi.testclient import TestClient

def run_tests():
    print("1. Testing LAN IP detection...")
    lan_ip = get_lan_ip()
    print(f"   Detected LAN IP: {lan_ip}")
    assert lan_ip, "LAN IP should not be empty"

    print("2. Testing Brain directory...")
    print(f"   Brain path: {DEFAULT_BRAIN_DIR}")
    assert DEFAULT_BRAIN_DIR.exists(), f"Brain directory {DEFAULT_BRAIN_DIR} should exist"

    print("3. Testing FastAPI endpoints with TestClient...")
    client = TestClient(app)

    # Info without token -> 401
    resp = client.get("/api/info")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    # Info with token -> 200
    resp = client.get(f"/api/info?token={AUTH_TOKEN}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    info = resp.json()
    print(f"   Info response: {info['hostname']} | status: {info['status']}")

    # Conversations list
    resp = client.get(f"/api/conversations?token={AUTH_TOKEN}")
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    print(f"   Found {len(convs)} conversations in brain.")
    if convs:
        c0 = convs[0]
        print(f"   Latest conversation: {c0['id'][:8]}... | Status: {c0['status']} | Title: {c0['title'][:30]}")

    # QR Code generator
    resp = client.get("/api/qrcode?text=https://antigravity.google")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    print(f"   QR Code generated: {len(resp.content)} bytes PNG")

    # Mobile Web UI
    resp = client.get(f"/?token={AUTH_TOKEN}")
    assert resp.status_code == 200
    assert "AGY Pocket" in resp.text
    print("   Mobile HTML served successfully.")

    print("\n[SUCCESS] All PC Companion self-tests passed successfully!")

if __name__ == "__main__":
    run_tests()
