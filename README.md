# 专注记录 · Focus Ledger

自托管的多设备应用使用时间记录工具。Windows 和 Android 客户端记录前台应用，通过自己的服务器同步，在网页时间轴、应用排行和 Android 桌面小组件中查看。

支持中文界面、深浅色主题、离线缓存与多用户。采集需要用户主动配置并开启；不采集窗口标题、截图、键盘输入、文件内容或进程完整路径。

[Windows 使用说明](client/README.md) · [Android 使用说明](android/README.md) · [服务端部署](server/README.md) · [完整文档](docs/README.md) · [参与开发](CONTRIBUTING.md)

## 功能

- **多设备时间轴**：查看每台设备及同一用户所有设备的使用时段，支持缩放、拖动和应用筛选。
- **应用统计**：按日、周、月、年查看时长和排行，自定义应用名称与颜色。
- **实时状态**：展示当前应用、在线状态、电量和可选的当前音乐；网页通过 SSE 更新。
- **离线记录**：本地 SQLite 队列保存待上传记录，恢复连接后补传，服务端去重。
- **自行部署**：FastAPI + SQLite，提供 Docker Compose、离线镜像打包和标准接收协议。
- **移动查看**：网页适配手机；Android 客户端提供可缩放的原生桌面小组件。

当前版本：

| 组件 | 版本 | 支持环境 |
| --- | --- | --- |
| Windows 客户端 | 0.3.1 | Windows 10 / 11 x64 |
| Android 客户端 | 0.1.6（试用版） | Android 9+，小组件成员授权需服务端 r13+ |
| 服务端 | 2026.10.18-r17 | 发布镜像为 Linux x86_64 / amd64 |

## 界面预览

![网页设备看板](server/docs/server-live-apps-preview.jpg)

<details>
<summary>查看 Windows、Android 和深色界面</summary>

| Windows 客户端 | Android 客户端 |
| --- | --- |
| <img src="client/docs/client-preview.png" alt="Windows 客户端示例" width="680"> | <img src="android/docs/ui/light-0.png" alt="Android 客户端示例" width="240"> |

![网页深色模式](server/docs/server-dark-preview.png)

</details>

截图使用示例数据，部分来自较早版本；当前界面可能有所调整。更多预览见各组件说明。

## 下载与接入

在仓库的 **Releases** 页面获取维护者已上传的发布附件。源码仓库不保存安装包或 Docker 镜像，下载源码 ZIP 不会包含这些文件。尚未发布附件时，可按下方说明从源码运行。

| 发布附件 | 用途 |
| --- | --- |
| `FocusLedger-Setup-windows-x64.exe` | Windows 中文安装向导，推荐使用 |
| `FocusLedger.exe` / `FocusLedger-windows-x64.zip` | Windows 免安装版本 |
| `FocusLedger-android.apk` | Android 安装包 |
| `FocusLedger-server-docker.zip` | 包含镜像、配置与教程的服务端离线部署包 |
| `FocusLedger-server-linux-amd64.tar` | 单独的 Linux amd64 Docker 镜像 |

先[部署服务端](server/README.md)，创建用户并生成上传密钥；再在客户端填入服务端地址、密钥与设备名称，验证连接后开始采集。Android 还需按说明授予使用情况访问权限。各端 `release/` 中的校验清单用于核对附件，发布方式见[发布指南](docs/RELEASING.md)。

## 从源码开始

以下命令从项目根目录执行。Windows 使用 Python 3.12 x64；Android 构建需要 JDK 21、Android SDK Platform 36 和 Build Tools 36.0.0。

### 服务端

首次部署，在装有 Docker Engine 和 Compose 插件的 Linux amd64 机器上执行：

```bash
cd server
cp .env.example .env
# 编辑 .env，为 ADMIN_PASSWORD 设置 12–256 个字符的密码。
docker volume create focusledger-data
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

等待服务健康后访问 `http://服务器IP:8080`。公网使用 HTTPS 反向代理并设置 `SECURE_COOKIES=true`。**已有部署升级前，应保留原 `.env` 并核对旧数据卷名称**；完整的升级、面板部署和备份说明见[服务端教程](server/README.md)。

### Windows 客户端

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r client\requirements.txt
.\.venv\Scripts\python.exe client\main.py
```

安装包与免安装版的构建方法见 [Windows 说明](client/README.md#源码运行与打包)。Android 的权限、后台运行和签名构建见 [Android 说明](android/README.md)。

## 数据与可见范围

记录发送到用户配置的服务器。未开启公开时，设备记录可由该服务器的**所有已登录成员**查看；开启公开后，访客也可以查看。请根据实际使用范围设置账户和公开选项。

音乐同步为可选功能，只展示当前系统媒体会话，不录音、不上传通知正文、不保存听歌历史。Windows 上传密钥使用 DPAPI 加密，Android 使用 Android Keystore；服务端记录最长保留 365 天。详见[数据与隐私说明](docs/PRIVACY.md)。

目前适合小规模、单服务器部署，使用 SQLite WAL 和单个 Uvicorn worker。Android 的厂商后台限制、真机耗电和桌面小组件表现仍需实际设备验证；已完成的检查及限制见[验证记录](docs/VALIDATION.md)。

## 项目结构与开发

```text
android/      Android 客户端、Gradle 构建、测试和预览
client/       Windows 客户端、打包脚本、测试和预览
server/       FastAPI 服务端、网页、Docker 配置和测试
docs/         使用详解、协议入口、隐私与发布说明
tools/        联合打包与仓库发布前检查
.github/      自动检查、问题和合并请求模板
```

安装开发依赖与测试方法见[贡献指南](CONTRIBUTING.md)。GitHub Actions 配置包含 Windows Python 回归、网页 JavaScript 测试、服务端镜像构建及 Android 测试与 Lint；首次推送后可在 Actions 页面查看运行结果。

## 许可

项目原创代码采用 [GNU GPL-3.0 License](LICENSE)，版权所有 © 2026 **Mikefuck**。第三方代码和依赖沿用各自许可，见[第三方组件说明](docs/THIRD-PARTY-NOTICES.md)。
