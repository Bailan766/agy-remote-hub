"""
Antigravity Pocket - Desktop Companion Launcher GUI
Shows QR codes for mobile connection, APK download, and Google Remote Control link.
"""

import sys
import threading
import socket
import io
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QLineEdit, QCheckBox, QMessageBox, QFrame,
    QScrollArea, QTextEdit
)
from PySide6.QtGui import QPixmap, QImage, QFont, QColor, QClipboard
from PySide6.QtCore import Qt, QSize
import qrcode
import uvicorn

from server import app, CONFIG, AUTH_TOKEN, get_lan_ip, set_keep_awake, DIST_DIR, save_config, im_bridge, agent_runner
from quota_monitor import format_quota_report, get_antigravity_quota

class QrWidget(QWidget):
    def __init__(self, qr_text: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setFixedSize(260, 260)
        self.lbl_qr.setStyleSheet("background: white; border-radius: 12px; padding: 10px;")
        
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setStyleSheet("color: #a0aec0; font-size: 13px; margin-top: 10px;")
        self.lbl_sub.setWordWrap(True)
        
        layout.addWidget(self.lbl_qr)
        layout.addWidget(self.lbl_sub)
        
        self.update_qr(qr_text)

    def update_qr(self, text: str):
        if not text:
            self.lbl_qr.clear()
            return
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=1
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        
        qimg = QImage.fromData(buf.getvalue())
        pixmap = QPixmap.fromImage(qimg).scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_qr.setPixmap(pixmap)


class CompanionWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Antigravity Pocket - 手机控制连接中心")
        self.setFixedSize(520, 680)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #12151e;
            }
            QLabel {
                color: #e2e8f0;
                font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #2d3748;
                border-radius: 10px;
                background: #1a202c;
            }
            QTabBar::tab {
                background: #171923;
                color: #a0aec0;
                padding: 8px 10px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 12px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1a202c;
                color: #4e80ee;
                border-bottom: 2px solid #4e80ee;
            }
            QPushButton {
                background-color: #4e80ee;
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3b6cd4;
            }
            QPushButton:pressed {
                background-color: #2b5cb4;
            }
            QLineEdit, QTextEdit {
                background: #0f131a;
                border: 1px solid #2d3748;
                border-radius: 6px;
                padding: 7px;
                color: white;
                font-size: 12px;
            }
            QCheckBox {
                color: #cbd5e0;
                font-size: 12px;
            }
        """)

        self.lan_ip = get_lan_ip()
        self.port = CONFIG.get("port", 8765)
        self.hub_url = f"http://{self.lan_ip}:{self.port}/?token={AUTH_TOKEN}"
        self.apk_url = f"http://{self.lan_ip}:{self.port}/download/agy-pocket.apk"

        # Main widget & layout
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("⚡ Antigravity Pocket")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")
        
        status_box = QHBoxLayout()
        lbl_dot = QLabel("●")
        lbl_dot.setStyleSheet("color: #00d2aa; font-size: 14px;")
        self.lbl_status = QLabel(f"局域网服务运行中 ({self.lan_ip}:{self.port})")
        self.lbl_status.setStyleSheet("color: #00d2aa; font-size: 12px;")
        status_box.addWidget(lbl_dot)
        status_box.addWidget(self.lbl_status)
        status_box.addStretch()

        title_box.addWidget(lbl_title)
        title_box.addLayout(status_box)
        header.addLayout(title_box)
        header.addStretch()
        layout.addLayout(header)

        # Tabs
        self.tabs = QTabWidget()
        
        # Tab 1: Connect
        self.qr_connect = QrWidget(
            self.hub_url,
            "手机打开相机或 AGY Pocket 扫描即可连接控制"
        )
        self.tabs.addTab(self.qr_connect, "📱 扫码控制")

        # Tab 2: Download APK
        self.qr_apk = QrWidget(
            self.apk_url,
            "手机浏览器扫描直接下载安装 APK 安装包"
        )
        self.tabs.addTab(self.qr_apk, "📦 下载 App")

        # Tab 3: Official Remote Control Link
        tab_official = QWidget()
        tab_official_layout = QVBoxLayout(tab_official)
        tab_official_layout.setContentsMargins(10, 10, 10, 10)
        
        lbl_hint = QLabel("粘贴 Antigravity 官方生成的远程链接：")
        lbl_hint.setStyleSheet("font-size: 12px; color: #a0aec0;")
        self.txt_official = QLineEdit()
        self.txt_official.setPlaceholderText("例如: https://antigravity.google/...")
        self.txt_official.textChanged.connect(self.on_official_url_changed)
        
        self.qr_official = QrWidget("https://antigravity.google", "手机扫描打开官方 Remote Control")
        
        tab_official_layout.addWidget(lbl_hint)
        tab_official_layout.addWidget(self.txt_official)
        tab_official_layout.addWidget(self.qr_official)
        self.tabs.addTab(tab_official, "🌐 官方链接")

        # Tab 4: IM Bot Bridge (Telegram / Feishu / QQ)
        self.tabs.addTab(self._build_im_tab(), "🤖 IM 机器人")

        # Tab 5: Model Quota Monitor
        self.tabs.addTab(self._build_quota_tab(), "📊 模型用量")

        layout.addWidget(self.tabs)

        # Actions & Settings
        btn_box = QHBoxLayout()
        btn_copy = QPushButton("📋 复制控制链接")
        btn_copy.clicked.connect(self.copy_url)
        btn_browser = QPushButton("🌐 电脑端预览")
        btn_browser.setStyleSheet("background-color: #2d3748;")
        btn_browser.clicked.connect(self.open_in_browser)
        
        btn_box.addWidget(btn_copy)
        btn_box.addWidget(btn_browser)
        layout.addLayout(btn_box)

        # Footer keep awake
        self.chk_awake = QCheckBox("💡 保持电脑不休眠（保证远程控制与 IM 机器人不掉线）")
        self.chk_awake.setChecked(CONFIG.get("keep_awake", True))
        self.chk_awake.toggled.connect(self.on_awake_toggled)
        layout.addWidget(self.chk_awake)

    def _build_im_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        im_cfg = CONFIG.get("im_bridge") or {}
        tg_cfg = im_cfg.get("telegram") or {}
        fs_cfg = im_cfg.get("feishu") or {}
        qq_cfg = im_cfg.get("qq") or {}

        self.chk_im_enabled = QCheckBox("启用 IM 对话式机器人桥接（类似 OpenClaw）")
        self.chk_im_enabled.setChecked(bool(im_cfg.get("enabled", False)))
        v.addWidget(self.chk_im_enabled)

        self.txt_workspace = QLineEdit(CONFIG.get("workspace_dir", ""))
        self.txt_workspace.setPlaceholderText("默认工作区目录 (例如 D:\\Projects)")
        v.addWidget(QLabel("默认工作目录 (agy CLI):"))
        v.addWidget(self.txt_workspace)

        self.txt_model = QLineEdit(CONFIG.get("agy_model", ""))
        self.txt_model.setPlaceholderText("留空使用系统默认 (或填 gemini-4-neon 等)")
        v.addWidget(QLabel("默认对话模型 (--model):"))
        v.addWidget(self.txt_model)

        # Telegram
        self.chk_tg = QCheckBox("启用 Telegram Bot")
        self.chk_tg.setChecked(bool(tg_cfg.get("enabled", False)))
        v.addWidget(self.chk_tg)

        self.txt_tg_token = QLineEdit(tg_cfg.get("bot_token", ""))
        self.txt_tg_token.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.txt_tg_token.setPlaceholderText("Telegram Bot Token (@BotFather 获取)")
        v.addWidget(self.txt_tg_token)

        self.txt_tg_proxy = QLineEdit(tg_cfg.get("proxy_url", ""))
        self.txt_tg_proxy.setPlaceholderText("可选代理 URL (例如 http://127.0.0.1:7890)")
        v.addWidget(self.txt_tg_proxy)

        self.txt_tg_users = QLineEdit(",".join(str(x) for x in (tg_cfg.get("allowed_user_ids") or [])))
        self.txt_tg_users.setPlaceholderText("允许的 Telegram User ID，逗号分隔 (留空则首次私聊会提示 ID)")
        v.addWidget(self.txt_tg_users)

        # Feishu
        self.chk_fs = QCheckBox("启用飞书机器人 (WebSocket 长连接，无需公网 IP)")
        self.chk_fs.setChecked(bool(fs_cfg.get("enabled", False)))
        v.addWidget(self.chk_fs)

        self.txt_fs_id = QLineEdit(fs_cfg.get("app_id", ""))
        self.txt_fs_id.setPlaceholderText("飞书 App ID")
        v.addWidget(self.txt_fs_id)

        self.txt_fs_secret = QLineEdit(fs_cfg.get("app_secret", ""))
        self.txt_fs_secret.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.txt_fs_secret.setPlaceholderText("飞书 App Secret")
        v.addWidget(self.txt_fs_secret)

        self.txt_fs_users = QLineEdit(",".join(str(x) for x in (fs_cfg.get("allowed_open_ids") or [])))
        self.txt_fs_users.setPlaceholderText("允许的飞书 open_id，逗号分隔")
        v.addWidget(self.txt_fs_users)

        # QQ OneBot
        self.chk_qq = QCheckBox("启用 QQ 机器人 (OneBot v11 正向 WebSocket)")
        self.chk_qq.setChecked(bool(qq_cfg.get("enabled", False)))
        v.addWidget(self.chk_qq)

        self.txt_qq_ws = QLineEdit(qq_cfg.get("ws_url", "ws://127.0.0.1:3001"))
        self.txt_qq_ws.setPlaceholderText("OneBot WS 地址 (如 ws://127.0.0.1:3001)")
        v.addWidget(self.txt_qq_ws)

        self.txt_qq_token = QLineEdit(qq_cfg.get("access_token", ""))
        self.txt_qq_token.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.txt_qq_token.setPlaceholderText("可选 OneBot Access Token")
        v.addWidget(self.txt_qq_token)

        self.txt_qq_users = QLineEdit(",".join(str(x) for x in (qq_cfg.get("allowed_qq") or [])))
        self.txt_qq_users.setPlaceholderText("允许的 QQ 号，逗号分隔")
        v.addWidget(self.txt_qq_users)

        self.lbl_im_state = QLabel(self._format_im_state())
        self.lbl_im_state.setWordWrap(True)
        self.lbl_im_state.setStyleSheet("font-size: 11px; color: #a0aec0;")
        v.addWidget(self.lbl_im_state)

        btn_save_im = QPushButton("💾 保存并重启 IM 机器人")
        btn_save_im.clicked.connect(self.save_im_settings)
        v.addWidget(btn_save_im)

        v.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_quota_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        lbl = QLabel("实时读取本地 Antigravity 各模型剩余额度与重置倒计时：")
        lbl.setStyleSheet("font-size: 12px; color: #a0aec0;")
        v.addWidget(lbl)

        self.txt_quota = QTextEdit()
        self.txt_quota.setReadOnly(True)
        v.addWidget(self.txt_quota)

        btn_refresh = QPushButton("🔄 刷新模型用量")
        btn_refresh.clicked.connect(self.refresh_quota)
        v.addWidget(btn_refresh)

        self.refresh_quota()
        return w

    def _format_im_state(self) -> str:
        st = im_bridge.status()
        parts = []
        for key, name in (("telegram", "TG"), ("feishu", "飞书"), ("qq", "QQ")):
            item = st.get(key) or {}
            err = f" ({item['error']})" if item.get("error") else ""
            parts.append(f"{name}: {item.get('state', 'stopped')}{err}")
        return "当前状态: " + " | ".join(parts)

    def save_im_settings(self):
        split_csv = lambda s: [x.strip() for x in s.split(",") if x.strip()]
        im_cfg = CONFIG.setdefault("im_bridge", {})
        im_cfg["enabled"] = self.chk_im_enabled.isChecked()
        if self.txt_workspace.text().strip():
            CONFIG["workspace_dir"] = self.txt_workspace.text().strip()
        agent_runner.set_default_model(self.txt_model.text().strip())

        im_cfg["telegram"] = {
            "enabled": self.chk_tg.isChecked(),
            "bot_token": self.txt_tg_token.text().strip(),
            "proxy_url": self.txt_tg_proxy.text().strip(),
            "allowed_user_ids": split_csv(self.txt_tg_users.text()),
        }
        im_cfg["feishu"] = {
            "enabled": self.chk_fs.isChecked(),
            "app_id": self.txt_fs_id.text().strip(),
            "app_secret": self.txt_fs_secret.text().strip(),
            "allowed_open_ids": split_csv(self.txt_fs_users.text()),
        }
        im_cfg["qq"] = {
            "enabled": self.chk_qq.isChecked(),
            "ws_url": self.txt_qq_ws.text().strip(),
            "access_token": self.txt_qq_token.text().strip(),
            "allowed_qq": split_csv(self.txt_qq_users.text()),
        }
        save_config(CONFIG)
        im_bridge.reload()
        self.lbl_im_state.setText(self._format_im_state())
        QMessageBox.information(self, "已保存", "IM 机器人配置已保存并重新加载。")

    def refresh_quota(self):
        data = get_antigravity_quota(include_cli_fallback=False)
        self.txt_quota.setPlainText(format_quota_report(data))

    def on_official_url_changed(self, text: str):
        url = text.strip() or "https://antigravity.google"
        self.qr_official.update_qr(url)

    def copy_url(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.hub_url)
        QMessageBox.information(self, "已复制", f"已复制连接地址到剪贴板：\n{self.hub_url}")

    def open_in_browser(self):
        import webbrowser
        webbrowser.open(self.hub_url)

    def on_awake_toggled(self, checked: bool):
        set_keep_awake(checked)


def start_server_thread():
    im_bridge.start()
    port = CONFIG.get("port", 8765)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()

if __name__ == "__main__":
    # Start FastAPI in daemon thread
    t = threading.Thread(target=start_server_thread, daemon=True)
    t.start()
    
    # Start PySide6 Application
    qapp = QApplication(sys.argv)
    win = CompanionWindow()
    win.show()
    sys.exit(qapp.exec())
