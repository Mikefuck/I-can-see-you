# 专注记录 · Focus Ledger

Windows 前台应用使用记录客户端、原生 Android 试用客户端，以及面向 Linux Docker 的多用户服务端。

## 下载与快速开始

2026-10-16 客户端 **0.3.1** / 服务端 **2026.10.16-r12**：修复 Windows 音乐同步选项与启动设置重叠；支持 Windows / Android 当前音乐同步，网页沿用原有风格，实时显示歌曲、歌手、播放器与暂停状态。已包含当前应用栏、前台变化立即上传、SSE 网页实时刷新、gzip 压缩和 500 条补传批次。支持按程序着色的时间线和排行，客户端可选择协调配色、恢复单个或全部默认色；未设置时自动分配稳定颜色。服务端首页直接展示公开设备使用时间，无需登录；未公开记录仅供所有已登录成员查看，分别在「公开设备 / 成员可见」看板展示。客户端数值框和下拉选择框不再响应滚轮改值，滚轮继续用于页面滚动。保留同账户按设备名称识别、公网 / 内网双地址自动切换、深浅色主题、交互动画、系统进程批量选择和历史应用名同步。客户端支持 Windows 10 / 11 x64，服务端镜像支持 Linux x86_64 / amd64。

| 文件 | 用法 |
| --- | --- |
| [FocusLedger-android.apk](android/release/FocusLedger-android.apk) | Android 9+ 原生试用版 0.1.5，优化熄屏调度、音乐检测与数据库写入，取消默认申请状态通知权限，保留实时采集；[安装与小米配置说明](android/README.md) |
| [FocusLedger-Setup-windows-x64.exe](client/release/FocusLedger-Setup-windows-x64.exe) | 推荐：中文安装向导，可在 Windows 应用列表卸载，无需安装 Python |
| [FocusLedger.exe](client/release/FocusLedger.exe) | 客户端单文件版，双击运行，无需安装 Python |
| [FocusLedger-windows-x64.zip](client/release/FocusLedger-windows-x64.zip) | 客户端文件夹版，解压后运行 `FocusLedger/FocusLedger.exe` |
| [FocusLedger-server-docker.zip](server/release/FocusLedger-server-docker.zip) | 服务端完整离线部署包，包含镜像、Compose 配置、配置示例和教程 |
| [FocusLedger-server-linux-amd64.tar](server/release/FocusLedger-server-linux-amd64.tar) | 单独的 Docker 镜像，使用 `docker load -i` 导入 |

推荐先按下方教程部署服务端、创建用户并生成上传密钥，再运行客户端。各自 `release/SHA256SUMS.txt` 提供发布文件的 SHA-256 校验值；服务端 ZIP 内还包含镜像校验文件。

## 目录分类

```text
android/                      原生 Android 客户端、构建脚本、测试与 APK
client/                       Windows 客户端
├── main.py                   启动入口
├── focus_agent/              采集、缓存、上传与界面
├── requirements.txt          客户端依赖
├── build.ps1                 Windows 打包脚本（默认生成安装包）
├── build-installer.ps1       将文件夹版封装为安装包
├── installer/               安装、升级、卸载规则与中文向导
├── dist/FocusLedger.exe      单文件可执行程序
├── dist/FocusLedger/         可直接运行的程序
├── build/                    打包中间文件
├── tests/                    客户端与 GUI 测试
├── tools/preview_client.py   客户端预览工具
├── docs/                     客户端预览图片
└── release/                  客户端发布包与校验文件
server/                       Linux Docker 服务端
├── app/                      接口、数据库与网页
├── Dockerfile、compose*.yaml 部署与源码构建配置
├── build_image.py            构建并导出可 docker load 的镜像
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

- 当前音乐：Windows 0.3.1、Android 0.1.5 读取系统媒体会话中的歌名、歌手、专辑、播放器与播放 / 暂停状态，配合服务端 r12 在设备看板和成员记录页实时显示。支持后台播放，安卓熄屏听歌继续同步；不录音、不读取通知正文，不保存听歌历史。两端可关闭音乐同步，暂停采集也会停止同步。安卓需在「连接」页开启通知访问权限；Windows 播放器需支持并开启系统媒体控制。安卓上传时自动刷新服务端能力，升级后可点击「立即上传」触发检查；旧服务端不支持音乐时会明确提示。网页沿用现有时钟、字体、配色与时刻表布局。
- 程序配色：网页时间线、应用排行和使用记录按程序着色；客户端「设置 → 程序名称与颜色」可选择 12 种协调配色，未设置时自动分配稳定默认色，支持单个或全部恢复默认。配色按设备同步，覆盖历史记录，适配网页深浅色主题，离线自动重试。
- Windows GUI：公网 / 内网双地址（分别设置协议和端口，连接失败自动切换）、上传密钥、设备名称、启动方式、电池及关机/休眠上传选项、应用名翻译、实际上传连接测试、采集状态、最近记录。
- 客户端「服务端」页：登录后生成自己的上传密钥并自动接入；管理员可查看 / 创建 / 启停用户、修改数据保留天数。管理密码和会话只保存在内存；运行天数持久化到服务端数据库。端口映射与 HTTPS 证书仍由服务器部署配置管理。
- 每秒采样前台应用，记录应用名称、进程名、起止时间和使用秒数；商店（UWP）应用识别为实际应用进程，而不是 ApplicationFrameHost。按设置记录电池和系统生命周期状态。**不采集窗口标题、截图、键盘输入、文件内容或进程完整路径。**
- 登录 Windows 后启动、静默进入系统托盘、托盘打开设置 / 暂停 / 上传 / 退出；再次运行程序会唤出已在托盘运行的主窗口。首次使用必须配置后开始采集。
- 关机 / 注销、睡眠 / 休眠通过独立的隐藏系统窗口接收通知（静默启动、从未打开主窗口时同样有效）：先写入本地队列，再限时上传——关机最多等约3秒，睡眠最多约1.5秒，均不会阻止关机或睡眠；来不及上传的记录在下次联网后补传。
- 电池：按间隔记录电量、充电和电源状态，插拔电源时立即补记一条；台式机无电池时上报空值。关闭电池采集后，关机 / 睡眠节点仍会记录，但不含电池信息。
- 应用名翻译按进程名匹配，可省略 `.exe` 或粘贴完整路径；支持搜索并批量选择当前系统进程，也可双击最近记录快速添加。保存后立即同步当前设备的历史名称、时间线和排行，离线自动重试；历史同步需将服务端更新到 r5 或更新版本。
- 默认无键鼠操作5分钟后暂停，支持调整或关闭空闲检测；锁屏和休眠仍停止计时。
- 每30秒分段保存、默认每30秒上传；失败时保留 SQLite 队列，指数退避重试，服务端按记录 ID 去重。
- 管理员创建 / 停用 / 启用用户；普通用户独立登录、修改密码、生成自己的上传密钥。设备与上传权限按账户隔离：**公开记录无需登录即可查看，未公开记录仅供所有已登录成员查看**；在「账户」页设置本账户全部设备是否对访客公开。
- 客户端与服务端网页默认跟随各自设备的系统深浅色；顶部主题按钮可选「跟随系统 / 浅色 / 深色」，立即生效并记住选择。客户端保存到本机配置，网页保存到当前浏览器；主题不跨设备同步。
- 交互动画：客户端切页采用短暂淡入与方向过渡，导航、复选框、进程勾选和按钮有即时反馈；网页主导航、时间范围、设备筛选及主题菜单具有轻量过渡。遵循系统减少动态效果设置，连续操作以最后一次选择为准，自动刷新不重复播放页面入场。
- 服务端网页采用瑞士铁路时刻表风格，手机与电脑自适应，并尊重「减少动态效果」设置：
  - **设备看板**：首页默认展示公开设备，无需登录；「成员可见」入口需登录，展示未公开的设备。每台设备一条时间线，标出使用中 / 空闲 / 休眠 / 关机 / 离线、正在使用的应用、电量和今日时长；顶部统计当前看板的在线设备、正在使用人数和今日累计时长。鼠标或手指划过时间线可查看任一时刻的状态，每 30 秒自动刷新。
  - **我的记录 / 成员记录**：按日、周、月、年查看，可只看某台设备；日视图的时刻表、周 / 月的逐日时刻表、全年日历、应用排行（点选后在时刻表中突出显示）、每小时 / 每天 / 每月柱状图、使用记录和开关机记录。
  - **账户**（上传密钥、公开开关、设备、接入步骤、修改密码）与**成员**（管理员创建、停用账户）。
- 服务端最多保留365天，启动及每分钟清理；所有展示查询也实时限制保留范围。
- 标准 JSON 接收接口和明确版本，其他平台可以使用相同协议接入。

## Linux Docker 部署

将 `server/release/FocusLedger-server-docker.zip` 上传到 Linux x86_64 服务器。服务器需要事先安装 Docker Engine 和 Compose 插件；导入和运行发布包不需要联网下载依赖。

以下用于首次部署。已有服务请按 [服务端升级步骤](server/README.md#从旧版本升级--修改管理员密码) 将配置指向原数据卷，保留原 `.env`。

```bash
unzip FocusLedger-server-docker.zip
cd server
sha256sum -c IMAGE-SHA256SUMS.txt
docker load -i FocusLedger-server-linux-amd64.tar
cp .env.example .env
nano .env
docker volume create focusledger-data  # 首次部署；自定义卷名时与 FOCUSLEDGER_DATA_VOLUME 一致
docker compose up -d
docker compose ps
docker compose logs -f server
```

在 `.env` 填写 `ADMIN_USERNAME` 和 12–256 个字符的 `ADMIN_PASSWORD`（建议用英文单引号包住密码），默认网页端口为 `8080`。首次启动创建管理员；r4 起修改 Compose 密码并重新创建容器后，会同步更新对应管理员密码并注销该管理员的旧会话，记录和上传密钥保留。Compose 密码不变时，网页中修改的密码在重启后仍保留。从旧版升级到 r4 的第一次启动会采用当前 Compose 密码，请先检查它满足长度要求。可用 `SERVER_PORT` 修改端口，`RETENTION_DAYS` 设置初始1–365天；客户端管理页保存后以数据库中的天数为准。镜像标签为 `focusledger-server:2026.10.16-r12`，与 `.env` 的 `FOCUSLEDGER_IMAGE` 保持一致。

等待 `docker compose ps` 显示 `healthy` 后访问网页。日志查看时按 Ctrl+C 不会停止服务。源码目录内的单独镜像位于 `server/release/`；若在源码的 `server` 目录导入，请改用 `docker load -i release/FocusLedger-server-linux-amd64.tar`。**不能把 ZIP 直接传给 `docker load`。**

1. 打开 `http://服务器IP:8080`，使用管理员账户登录。
2. 在「成员」创建所需用户。
3. 每个用户登录自己的账户，在「账户」生成上传密钥。密钥原文只显示一次。设备记录默认仅登录成员可见；需要让未登录访客也能查看时，在同一页打开「公开」。
4. 在对应用户的 Windows 客户端填写服务器地址、端口、协议和上传密钥。

公网部署请用已有的 HTTPS 反向代理并设 `SECURE_COOKIES=true`。客户端地址填写证书匹配的域名，协议选 `https`、端口填反向代理端口（通常443）。反向代理将整个站点转发到容器8080端口，上传包限制至少2MiB；不要配置重定向作为客户端的最终地址。内网 HTTP 使用时，保持 `SECURE_COOKIES=false`。

标准配置把数据库保存在固定名称的外部数据卷，默认 `focusledger-data`，由 `.env` 中的 `FOCUSLEDGER_DATA_VOLUME` 指定；容器重建、Compose 项目改名和 `docker compose down -v` 都会保留此卷。**已有命名卷部署必须填写旧卷的实际名称（例如 `server_focus-data`），否则无法读取旧记录；旧版配置的 `down -v` 仍会删除其管理的卷。** 面板版使用编排文件同目录的 `focus-data` 文件夹，须先按服务端教程创建并设置 UID/GID `10001:10001` 的读写权限；从旧卷切换时先停服迁移完整数据，移动编排文件时也要迁移该文件夹。如保留备份，备份也需执行相同的最长一年保留策略。

更新、备份、HTTPS、参数说明和故障处理见 [服务端完整教程](server/README.md)。默认 Compose 使用已导入镜像；从源码部署请在 `server` 目录运行 `docker compose -f compose.yaml -f compose.build.yaml up -d --build`。

## Windows 使用

推荐双击 `client/release/FocusLedger-Setup-windows-x64.exe`，按照中文向导安装。默认安装在 `%LOCALAPPDATA%\Programs\FocusLedger`，仅供当前 Windows 用户使用，无需管理员权限。安装后从开始菜单打开「专注记录」，也可在安装时选择创建桌面快捷方式。

以后直接运行新版安装包覆盖升级。卸载可使用 Windows「设置 → 应用 → 已安装的应用」（Windows 10 为「应用和功能」）中的「专注记录 · Focus Ledger」，或开始菜单中的「卸载专注记录」。安装 / 升级 / 卸载前先从系统托盘右键退出程序。卸载会清理程序、快捷方式及对应启动项，保留 `%LOCALAPPDATA%\FocusLedger` 中的配置与缓存；需要彻底清除本机数据时再手动删除该目录。

原有免安装版配置可直接沿用，已有自动启动路径会在安装时迁移，并保留启用 / 禁用状态。确认安装版正常后可删除旧免安装程序。仍需要单文件版时可运行 `client/release/FocusLedger.exe`；首次启动会解压内置运行库，可能等待数秒。

也可以使用 `client/release/FocusLedger-windows-x64.zip`，解压后运行 `FocusLedger/FocusLedger.exe`。文件夹版必须保留**整个 FocusLedger 文件夹**和 `_internal` 依赖目录，不能只取其中的小 EXE。两种版本共用配置与队列。

1. 在 GUI 中填写服务器主地址、端口、协议、上传密钥和设备名称；已有公网连接时保留原主地址，将内网 IP、端口和协议填入备用地址。两个地址须指向同一服务端，连接失败时自动切换，备用留空时沿用单地址。
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

默认生成 `client/release/FocusLedger-Setup-windows-x64.exe` 和校验值，构建电脑还需要 [Inno Setup](https://jrsoftware.org/isdl.php)（推荐 6.7.3 或更高版本）；可用 `-Iscc` 指定编译器路径。安装包内含完整运行库，目标电脑无需 Python 或 Inno Setup。

加 `-Package all` 同时生成免安装单文件与文件夹版；加 `-Package portable` 则仅构建免安装版本，可搭配 `-Layout onefile` 或 `-Layout onedir`。已有 `client/dist/FocusLedger/` 时可运行 `client/build-installer.ps1` 重新封装安装包。

只发布客户端执行 `python tools/package_release.py --client-only`；加 `--portable` 可同时发布已构建的免安装版。完整联合发布先用 `-Package all` 构建客户端，并执行 `python server/build_image.py` 导出服务端镜像（需要可用的 Linux Docker 引擎），最后执行：

```powershell
python tools/package_release.py
Get-FileHash client\release\FocusLedger-Setup-windows-x64.exe -Algorithm SHA256
```

打包工具会把 EXE、ZIP 和镜像校验文件写到两端各自的 `release` 目录。构建过程中需要联网，发布后的客户端和服务端不依赖本机 Python 环境。

免安装版本移动位置后，从新位置运行一次程序即可自动更新开机启动路径。删除免安装版本前取消开机启动、保存并退出，再删除程序文件。安装版使用系统卸载入口即可。

## 账户切换与缓存

首次保存 / 更换服务器或密钥 / 修改设备名称时必须成功验证连接，保证队列绑定的是确定的服务器、账户和设备。已验证的账户可以离线修改上传间隔等其他设置。

更新至客户端 0.2.6 / 服务端 r7 后，服务端在同一账户内按设备名称识别设备（忽略名称首尾空白），客户端版本不参与设备区分。同一 Windows 电脑升级或重新安装客户端，即使客户端设备 ID 改变，也会沿用该名称的历史记录；另一台电脑使用同名时，客户端提示「设备名称已被占用」，需改名后保存。不同账户可以使用相同名称。服务端首次启动会合并旧版遗留的同账户同名设备，保留历史记录和旧 ID 的补传能力。

- 同一账户重置密钥：队列和设备 ID 保持，更新密钥后补传。
- 同一服务端的公网 / 内网地址：在原主地址旁添加备用地址，自动切换时设备 ID 与队列保持；双地址都不可用时继续本地缓存。
- 切换到不同账户或服务器：使用新的设备 ID，旧队列保留在原连接下，不会被发给新账户。
- 切回原账户可以继续补传其旧队列；清空缓存前客户端会要求确认。
- 同一设备 UUID 不能同时属于两个账户。

## 协议与扩展

详见 [server/docs/API.md](server/docs/API.md)。后续 Linux / macOS / 手机等客户端可发送相同的 `app_usage` 和 `device_status` 数据包，指定自己的 `platform`。新增记录种类时应扩展服务端模型与数据库迁移，并根据兼容性提升 `schema_version` 或 API 版本。

当前为小规模、单服务器示例：SQLite WAL 和一个 Uvicorn worker。更多并发设备可迁移到 PostgreSQL、独立清理任务和分布式限流。安卓试用客户端说明见 [android/README.md](android/README.md)；当前不包含远程命令或客户端自动升级。

## 验证

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

测试覆盖数据去重、事务回滚、用户隔离、设备归属、密钥轮换、会话失效、CSRF、请求大小、时间校验、保留期、缓存恢复、设备状态、应用名翻译以及休眠 / 时钟跳变。Windows 下另验证 DPAPI 配置、电池读取与取值规范化、隐藏系统窗口能收到关机 / 睡眠广播，以及关机、睡眠、唤醒的去重与限时上传。

可分别运行 `python -m pytest client/tests` 和 `python -m pytest server/tests`；真实 HTTP 上传联调测试位于 `server/tests/test_upload_integration.py`，需要安装两端依赖。

重新生成两端发布包：先运行客户端 `build.ps1` 和服务端 `build_image.py`，再在项目根目录执行 `python tools/package_release.py`。发布包与 SHA-256 校验文件会分别写入 `client/release` 和 `server/release`。

自动化测试、浏览器检查与发布包验证结果见 [docs/VALIDATION.md](docs/VALIDATION.md)。

采样精度约1秒，正常退出前保存当前段，异常终止最多丢失最近约30秒。默认空闲检测依赖键鼠活动，观看视频时可调整空闲阈值。受保护的系统进程无法读取时跳过。服务端判定为格式无效的个别记录会标记为「服务器拒收」并保留在本地，不再阻塞其他记录上传。设备时钟需正常同步，超前5分钟的上传会被拒绝。服务端网页和客户端列表都按查看者本机时区显示时间（网页由浏览器换算，页脚注明当前时区）；服务端存储和接口使用 UTC。

实现依据：[Windows 前台窗口 API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow)、[空闲检测 API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)、[Qt 托盘 API](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)、[FastAPI Docker 部署文档](https://fastapi.tiangolo.com/deployment/docker/)。
