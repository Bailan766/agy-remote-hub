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
    QLabel, QPushButton, QTabWidget, QLineEdit, QCheckBox, QMessageBox, QFrame
)
from PySide6.QtGui import QPixmap, QImage, QFont, QColor, QClipboard
from PySide6.QtCore import Qt, QSize
import qrcode
import uvicorn

from server import app, CONFIG, AUTH_TOKEN, get_lan_ip, set_keep_awake, DIST_DIR

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
        self.setFixedSize(480, 620)
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
                padding: 10px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 13px;
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
            QLineEdit {
                background: #0f131a;
                border: 1px solid #2d3748;
                border-radius: 6px;
                padding: 8px;
                color: white;
                font-size: 12px;
            }
            QCheckBox {
                color: #cbd5e0;
                font-size: 13px;
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
        self.tabs.addTab(self.qr_connect, "📱 手机扫码控制")

        # Tab 2: Download APK
        self.qr_apk = QrWidget(
            self.apk_url,
            "手机浏览器扫描直接下载安装 APK 安装包"
        )
        self.tabs.addTab(self.qr_apk, "📦 下载手机 App")

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
        self.tabs.addTab(tab_official, "🌐 官方链接转二维码")

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
        self.chk_awake = QCheckBox("💡 保持电脑不休眠（保证远程控制不掉线）")
        self.chk_awake.setChecked(CONFIG.get("keep_awake", True))
        self.chk_awake.toggled.connect(self.on_awake_toggled)
        layout.addWidget(self.chk_awake)

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
