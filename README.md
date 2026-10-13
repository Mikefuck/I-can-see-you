# 专注记录 · Focus Ledger

一套可运行的 Windows 前台应用使用记录客户端，以及面向 Linux Docker 的多用户服务端。

## 目录分类

```text
client/                       Windows 客户端
├── main.py                   启动入口
├── focus_agent/              采集、缓存、上传与界面
├── requirements.txt          客户端依赖
├── build.ps1                 Windows 打包脚本
├── dist/FocusLedger/         可直接运行的程序
├── build/                    打包中间文件
├── tests/                    客户端与 GUI 测试
├── tools/preview_client.py   客户端预览工具
├── docs/                     客户端预览图片
└── release/                  客户端发布包与校验文件
server/                       Linux Docker 服务端
├── app/                      接口、数据库与网页
├── Dockerfile、compose.yaml  部署配置
├── requirements.txt          服务端依赖
├── tests/                    服务端与客户端上传联调测试
├── tools/demo_server.py      服务端演示工具
├── docs/                     API 协议与网页预览图片
└── release/                  服务端发布包与校验文件
docs/                         共用验证记录与第三方组件说明
tools/package_release.py      联合打包工具
.runtime/                     本地开发环境与验证缓存
```

客户端使用说明见 [client/README.md](client/README.md)，服务端部署说明见 [server/README.md](server/README.md)。两端源码、依赖、测试、工具和发布包分别归入对应目录，根目录的 `requirements-dev.txt` 与 `pytest.ini` 用于统一安装开发依赖和运行测试。

## 已实现

- Windows GUI：服务器 IP / 域名、端口、HTTP / HTTPS、上传密钥、设备名称、启动方式、电池及关机/休眠上传选项、应用名翻译、连接测试、采集状态、最近记录。
- 每秒采样前台应用，记录应用名称、进程名、起止时间和使用秒数；商店（UWP）应用识别为实际应用进程，而不是 ApplicationFrameHost。按设置记录电池和系统生命周期状态。**不采集窗口标题、截图、键盘输入、文件内容或进程完整路径。**
- 登录 Windows 后启动、静默进入系统托盘、托盘打开设置 / 暂停 / 上传 / 退出；再次运行程序会唤出已在托盘运行的主窗口。首次使用必须配置后开始采集。
- 关机 / 注销、睡眠 / 休眠通过独立的隐藏系统窗口接收通知（静默启动、从未打开主窗口时同样有效）：先写入本地队列，再限时上传——关机最多等约3秒，睡眠最多约1.5秒，均不会阻止关机或睡眠；来不及上传的记录在下次联网后补传。
- 电池：按间隔记录电量、充电和电源状态，插拔电源时立即补记一条；台式机无电池时上报空值。关闭电池采集后，关机 / 睡眠节点仍会记录，但不含电池信息。
- 应用名翻译按进程名匹配，可省略 `.exe` 或粘贴完整路径；双击最近记录可快速添加。
- 默认无键鼠操作5分钟后暂停，支持调整或关闭空闲检测；锁屏和休眠仍停止计时。
- 每30秒分段保存、默认每30秒上传；失败时保留 SQLite 队列，指数退避重试，服务端按记录 ID 去重。
- 管理员创建 / 停用 / 启用用户；普通用户独立登录、修改密码、生成自己的上传密钥。设备与数据按账户隔离。
- 示例网页：设备概览、时间 / 设备筛选、应用使用排行、最近100条记录、账户与密钥、用户管理。
- 服务端最多保留365天，启动及每分钟清理；所有展示查询也实时限制保留范围。
- 标准 JSON 接收接口和明确版本，其他平台可以使用相同协议接入。

## Linux Docker 部署

将 `server` 目录复制到 Linux 服务器。服务器需要 Docker Engine 和 Compose 插件。

```bash
cd server
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f server
```

在 `.env` 填写 `ADMIN_USERNAME` 和至少12个字符的 `ADMIN_PASSWORD`，默认网页端口为 `8080`。首次启动创建管理员；已有数据库时不会通过环境变量覆盖密码。可用 `SERVER_PORT` 修改端口，`RETENTION_DAYS` 设置1–365天。

1. 打开 `http://服务器IP:8080`，使用管理员账户登录。
2. 在「用户管理」创建所需用户。
3. 每个用户登录自己的账户，在「账户与密钥」生成上传密钥。密钥原文只显示一次。
4. 在对应用户的 Windows 客户端填写服务器地址、端口、协议和上传密钥。

公网部署请用已有的 HTTPS 反向代理并设 `SECURE_COOKIES=true`。客户端地址填写证书匹配的域名，协议选 `https`、端口填反向代理端口（通常443）。反向代理将整个站点转发到容器8080端口，上传包限制至少2MiB；不要配置重定向作为客户端的最终地址。内网 HTTP 使用时，保持 `SECURE_COOKIES=false`。

数据库保存在 Docker 命名卷 `focus-data`，容器重建后仍保留。`docker compose down` 保留数据，**`docker compose down -v` 会删除数据**。如保留备份，备份也需执行相同的最长一年保留策略。

## Windows 使用

已打包的程序位于 `client/dist/FocusLedger/FocusLedger.exe`。请复制**整个 FocusLedger 文件夹**到稳定位置，然后运行里面的 exe；无需另装 Python。

也可以使用 `client/release/FocusLedger-windows-x64.zip`。服务端部署包为 `server/release/FocusLedger-server-docker.zip`。各自目录中的 `SHA256SUMS.txt` 可用于校验发布包。

1. 在 GUI 中填写服务器 IP / 域名、端口、协议、上传密钥和设备名称。
2. 点击「保存设置」，首次保存会联网验证账户。
3. 点击「开始采集」。关闭窗口后仍在系统托盘运行；从托盘右键可以暂停或退出。
4. 勾选「登录 Windows 后自动启动」和 / 或「静默启动」，再次保存。开机启动实际发生在**当前用户登录后**，不需要管理员权限。

后续启动已配置的客户端会自动采集。采集暂停只影响采样，已有队列继续上传；需要完全停止程序时从托盘退出。静默模式保留托盘图标；没有可用托盘时自动显示主窗口，避免无法控制。

`FocusLedger.exe --show` 强制显示主窗口，`--silent` 强制托盘启动。已运行时再次运行程序会打开已有实例的主窗口，不会重复采集。

「自动启动」复选框显示 Windows 的实际状态：如果在任务管理器或「设置 › 应用 › 启动」中关闭了它，复选框会显示为未勾选并给出提示；重新勾选并保存即可恢复。

配置与队列在 `%LOCALAPPDATA%\FocusLedger`：上传密钥用当前 Windows 账户的 DPAPI 加密，不以明文保存。未上传缓存最多30天 / 100,000条，已上传的本地记录最多7天。日志只记录错误并限制大小。

### 从源码运行 / 打包

推荐 Python 3.12 x64，Windows 10 / 11 x64：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r client\requirements.txt
.\.venv\Scripts\python.exe client\main.py
.\client\build.ps1 -Python (Resolve-Path .venv\Scripts\python.exe).Path
```

移动程序文件夹后，从新位置运行一次程序即可自动更新开机启动路径。卸载前取消开机启动、保存并退出，之后删除程序文件夹；是否保留 `%LOCALAPPDATA%\FocusLedger` 由你决定。

## 账户切换与缓存

首次保存 / 更换服务器或密钥时必须成功验证连接，保证队列绑定的是确定的服务器和账户。已验证的账户可以离线修改设备名称、上传间隔等其他设置。

- 同一账户重置密钥：队列和设备 ID 保持，更新密钥后补传。
- 切换到不同账户或服务器：使用新的设备 ID，旧队列保留在原连接下，不会被发给新账户。
- 切回原账户可以继续补传其旧队列；清空缓存前客户端会要求确认。
- 同一设备 UUID 不能同时属于两个账户。

## 协议与扩展

详见 [server/docs/API.md](server/docs/API.md)。后续 Linux / macOS / 手机等客户端可发送相同的 `app_usage` 和 `device_status` 数据包，指定自己的 `platform`。新增记录种类时应扩展服务端模型与数据库迁移，并根据兼容性提升 `schema_version` 或 API 版本。

当前为小规模、单服务器示例：SQLite WAL 和一个 Uvicorn worker。更多并发设备可迁移到 PostgreSQL、独立清理任务和分布式限流；当前不包含移动端采集、远程命令或客户端自动升级。

## 验证

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

测试覆盖数据去重、事务回滚、用户隔离、设备归属、密钥轮换、会话失效、CSRF、请求大小、时间校验、保留期、缓存恢复、设备状态、应用名翻译以及休眠 / 时钟跳变。Windows 下另验证 DPAPI 配置、电池读取与取值规范化、隐藏系统窗口能收到关机 / 睡眠广播，以及关机、睡眠、唤醒的去重与限时上传。

可分别运行 `python -m pytest client/tests` 和 `python -m pytest server/tests`；真实 HTTP 上传联调测试位于 `server/tests/test_upload_integration.py`，需要安装两端依赖。

重新生成两端发布包：在项目根目录执行 `python tools/package_release.py`。请先运行客户端的 `build.ps1`，发布包与 SHA-256 校验文件会分别写入 `client/release` 和 `server/release`。

本次65项测试通过。完整验证范围与预览见 [docs/VALIDATION.md](docs/VALIDATION.md)，Linux Docker 容器尚未在本机实测。

采样精度约1秒，正常退出前保存当前段，异常终止最多丢失最近约30秒。默认空闲检测依赖键鼠活动，观看视频时可调整空闲阈值。受保护的系统进程无法读取时跳过。服务端判定为格式无效的个别记录会标记为「服务器拒收」并保留在本地，不再阻塞其他记录上传。设备时钟需正常同步，超前5分钟的上传会被拒绝。服务端示例的时间统一为 UTC，客户端列表展示本地时间。

实现依据：[Windows 前台窗口 API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow)、[空闲检测 API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)、[Qt 托盘 API](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)、[FastAPI Docker 部署文档](https://fastapi.tiangolo.com/deployment/docker/)。
