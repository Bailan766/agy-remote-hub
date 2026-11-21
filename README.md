# ⚡ Antigravity Pocket (AGY Remote Hub)

> 手机远程控制电脑端 **Google Antigravity** 的全套解决方案（包含 Android 原生控制客户端 APK、桌面配套二维码启动器与局域网实时桥接服务）。

---

## ✨ 核心特性

- 📱 **Android 手机客户端 (AGY Pocket APK)**：
  - **快速扫码直连**：内置相机扫码功能，扫描电脑屏幕二维码即可秒级建立连接。
  - **双模式支持**：既支持 Google 官方 `https://antigravity.google` Remote Control 链接，也支持局域网直连模式。
  - **设备与历史管理**：自动记忆常用电脑与连接历史，下次打开一键直连，无需反复扫码。
  - **快捷操作舵 (Quick Action Dock)**：底部常驻横向快捷指令栏，一键注入 `/plan`、`/goal`、`/compact`、`Proceed (同意)`、`⚡ /boost` 等高频操作。
  - **常亮与后台提醒**：支持一键保持手机屏幕常亮，防止远程监视任务时手机自动锁屏。

- 💻 **电脑端配套启动器与局域网服务 (`pc-companion/`)**：
  - **桌面二维码控制台 (PySide6)**：一键启动桌面小窗口，展示局域网直连二维码与手机扫码下载 APK 二维码。
  - **官方链接转二维码**：支持将官方生成的远程控制长链接粘贴到窗口中，自动生成大号二维码供手机扫描。
  - **会话与产物实时同步**：直接读取本地 Antigravity 会话记录与生成的 Markdown 产物文档（如实施方案、分析报告）。
  - **桌面实景流与触控映射**：在手机上可实时查看电脑端 Antigravity 窗口画面，在手机屏幕点击即可远程操控电脑按钮。
  - **防休眠机制**：自动调用 Windows API 阻止电脑在远程运行任务期间进入睡眠。
  - **📊 模型用量与额度监控**：直连本地 Antigravity `language_server` 实时读取各模型剩余配额百分比、重置倒计时与 Prompt Credits，可在桌面端、手机 Web 端或聊天机器人中随时查看。
  - **🤖 类 OpenClaw 多平台 IM 对话桥接**：内置 **Telegram Bot（长轮询）**、**飞书机器人（WebSocket 长连接）**、**QQ 机器人（OneBot v11）**，无需公网 IP 即可在聊天窗口直接发指令执行任务（调用 `agy` CLI 或注入桌面窗口）、查看截图与模型用量。

---

## 🛠️ 项目结构

```text
agy-remote-hub/
├── start_companion.bat            # 电脑端一键启动脚本 (双击运行)
├── pc-companion/                  # 电脑端配套启动器与局域网服务
│   ├── launcher_gui.py            # PySide6 桌面控制中心（二维码 / IM配置 / 用量监控）
│   ├── server.py                  # FastAPI 局域网桥接与实时推流服务
│   ├── quota_monitor.py           # Antigravity 本地模型用量与额度检测模块
│   ├── agent_runner.py            # 类 OpenClaw 对话式指令与 agy CLI 路由引擎
│   ├── im_bridge.py               # Telegram / 飞书 / QQ(OneBot) 多通道机器人网关
│   ├── static/
│   │   └── mobile_ui.html         # 手机 Web 响应式控制界面（含模型用量与对话测试）
│   ├── dist/
│   │   └── agy-pocket.apk         # 手机端 APK 安装包 (扫码直接下载)
│   ├── requirements.txt           # Python 依赖清单
│   └── test_server.py             # 服务端自检测试脚本
└── android-app/                   # Android 原生应用 (Kotlin + Jetpack Compose)
    ├── app/
    │   └── src/main/
    │       ├── AndroidManifest.xml
    │       └── kotlin/com/agy/pocket/
    │           ├── MainActivity.kt
    │           ├── Navigation.kt
    │           ├── data/ConnectionModel.kt
    │           └── ui/
    │               ├── HomeScreen.kt          # 扫码与设备列表
    │               └── RemoteControlScreen.kt # 全屏控制与快捷指令栏
    └── build.gradle.kts
```

---

## 🚀 快速上手

### 1. 电脑端启动

直接双击运行根目录下的 `start_companion.bat`（或在终端运行）：

```bash
cd pc-companion
pip install -r requirements.txt
python launcher_gui.py
```

桌面将弹出控制中心窗口，包含 5 个标签页：
1. **📱 扫码控制**：包含当前电脑局域网 IP 与安全访问令牌的二维码。
2. **📦 下载 App**：手机相机扫描即可直接下载安装 `AntigravityPocket.apk`（无需数据线连接）。
3. **🌐 官方链接**：可将官方 Remote Control 链接转为二维码。
4. **🤖 IM 机器人**：填写 Telegram Bot Token / 飞书 AppID+Secret / QQ OneBot WS 地址及白名单 ID，保存即可启用外网对话式控制。
5. **📊 模型用量**：一键刷新本地 Antigravity 各模型剩余额度与重置倒计时。

### 2. IM 机器人对话指令（Telegram / 飞书 / QQ）

- 直接发送任意自然语言：调用本机 `agy` CLI（支持上下文续聊；未安装 `agy` 时自动注入桌面端 Antigravity 窗口）
- `/usage` 或 `用量`：查看各模型剩余额度百分比与重置倒计时
- `/models`：查看可切换的模型列表（带序号与当前剩余额度）
- `/model <序号或名称>`：切换对话模型（`/model default` 恢复默认模型）
- `/status`：查看电脑状态、当前工作目录与最近会话
- `/screen` 或 `截图`：抓取并回传当前电脑桌面截图
- `/desktop <指令>`：直接向桌面端 Antigravity 窗口输入并提交
- `/approve`（同意） / `/cancel`（取消）：快捷审批桌面端弹窗
- `/cd <路径>` / `/pwd` / `/new` / `/mode <auto|accept-edits|plan|default>`：切换工作目录、开启新会话或切换模式

### 3. 手机端连接

1. 在手机上打开 **AGY Pocket** 应用（或手机浏览器扫码进入 Web UI，切换到 **“用量与Bot”** 标签也可查看模型配额）。
2. 点击 **“📷 扫描连接二维码”**，对准电脑窗口扫描即可瞬间进入远程控制界面。
3. 底部快捷栏点击 **“/plan”** 或 **“Proceed”**，电脑端 Antigravity 即可实时响应！

---

## 📄 开源许可

[MIT License](LICENSE)
