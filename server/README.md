# Linux Docker 服务端 · Focus Ledger

发布目标：**Linux x86_64 / amd64**（Intel / AMD），镜像标签 `focusledger-server:2026.10.16-r12`。镜像内已包含 Python、服务端依赖和网页，部署时无需安装 Python，也无需联网拉取基础镜像。目标服务器需事先安装 Docker Engine 和 Docker Compose 插件。

本版为设备时间线、应用排行和使用记录加入程序配色。未设置时自动分配稳定默认色；客户端 0.2.8 的「设置 → 程序名称与颜色」可为本设备修改颜色，或恢复单个 / 全部默认色，保存后同步历史记录。12 种预设色分别适配网页浅色与深色主题。

本版的设备看板与个人记录页新增「当前应用」栏，集中显示正在使用的前台应用名称、所属设备和最近上报时间，沿用原有时钟与时刻表布局。当前状态通过 SSE 实时更新，并每 10 秒独立校验，并兼容深浅色与手机；实际更新速度取决于客户端上传间隔。本次 Docker 发布包已包含这些功能。

上传接口支持协商 gzip 压缩，配套客户端可减少上传流量；旧客户端继续使用普通 JSON。服务端对压缩体和解压后的 JSON 均执行 2MiB 上限，500 条批次限制、鉴权、事件确认和去重规则保持一致。需同时更新客户端 0.2.9 和服务端 r10，协议见 [docs/API.md](docs/API.md)。

## 使用离线发布包（推荐）

r12 支持当前音乐：配套 Windows 0.3.0 / Android 0.1.3 上报歌名、歌手、专辑、播放器和播放 / 暂停状态。设备看板与成员记录页沿用原有视觉布局，在「当前应用与音乐」及设备栏显示歌曲，后台播放器也会展示。数据遵循原账户可见范围，经 SSE 实时刷新；失联或采样过期（最长 330 秒）后隐藏，暂停采集与正常停止时主动清除。不上传音频、不保存听歌历史，只保存各设备最新一份状态，自动兼容旧数据库。升级时继续使用原数据卷与管理员配置，将 `.env` 中镜像标签改为 `focusledger-server:2026.10.16-r12`，按下方升级步骤重新部署；安卓随后重新验证保存连接。

音乐展示预览（隔离的演示数据）：[桌面](docs/music-desktop.jpg)、[手机](docs/music-mobile.jpg)。

把 `server/release/FocusLedger-server-docker.zip` 上传至服务器。该包包含可直接导入的镜像、配置示例、本教程和源码。

以下步骤用于首次部署。已有服务请先阅读「从旧版本升级 / 修改管理员密码」，确认原数据卷名称并保留原 `.env`，再更新配置。

```bash
unzip FocusLedger-server-docker.zip
cd server
sha256sum -c IMAGE-SHA256SUMS.txt
docker load -i FocusLedger-server-linux-amd64.tar
cp .env.example .env
nano .env
```

在与 `compose.yaml` 同目录的 `.env` 中填写 `ADMIN_PASSWORD`，密码为 12–256 个字符。管理员用户名默认 `admin`；如需修改，设置 `ADMIN_USERNAME`，只允许 3–40 位英文字母、数字、`_`、`.`、`-`，不能使用中文或空格。建议把密码用英文单引号包起来，例如 `ADMIN_PASSWORD='你自己设置的长密码'`，避免密码中的 `$` 被 Compose 当作变量。不要把 `.env` 分享给其他人。

```bash
docker volume create focusledger-data  # 仅首次部署；自定义卷名时与 FOCUSLEDGER_DATA_VOLUME 一致
docker compose up -d
docker compose ps
docker compose logs --tail=100 server
```

等待状态变为 `healthy`，然后打开 `http://服务器IP:8080`。检查接口可执行 `curl -f http://127.0.0.1:8080/healthz`。首次启动会创建管理员；r4 起修改 `.env` / Compose 密码并重新创建容器后，会同步更新对应管理员密码，保留用户、记录和上传密钥。

如果直接使用本项目源码目录和单独的镜像文件，则在项目的 `server` 目录执行 `docker load -i release/FocusLedger-server-linux-amd64.tar`，之后同样复制 `.env.example`、修改 `.env` 并启动。

`FocusLedger-server-linux-amd64.tar` 才是 `docker load` 的输入，不能把外层 ZIP 直接交给 Docker。默认 Compose 使用本地镜像且禁止自动拉取；不需要加 `--build`。

## 在面板中粘贴 Compose 配置

如果面板报 `required variable ADMIN_PASSWORD is missing a value`，说明它没有读到 `.env` 中的密码。可使用无需 `.env` 的 [compose.panel.yaml](compose.panel.yaml)：先导入镜像，再把文件内容粘贴到原编排项目，将 `ADMIN_PASSWORD` 的占位文字替换成自己设置的 12–256 位密码，保存并重新部署。

面板版把编排文件同目录的 `./focus-data` 文件夹挂载到容器 `/data`，数据库位于该文件夹中的 `focus.sqlite3`。相对路径以面板实际保存编排文件的目录为准；在面板中确认该目录后，进入服务器终端执行以下命令。服务使用 UID/GID `10001:10001`，需要对目录及数据库文件有读写权限：

```bash
cd /实际的编排文件所在目录
sudo mkdir -p ./focus-data
sudo chown -R 10001:10001 ./focus-data
sudo chmod -R u+rwX ./focus-data
```

如果已经是 root 用户，可以省略 `sudo`。本配置使用 `create_host_path: false`，目录缺失时会明确报错；创建并设置权限后再在面板重新部署。这里不需要创建 Docker 命名卷，也不读取 `FOCUSLEDGER_DATA_VOLUME`。服务级的 `read_only: true` 可以保留，`/data` 挂载单独设置为可写。

**已有数据时**：若当前已经挂载同一个 `./focus-data`，停服后修正该文件夹的权限即可。若原数据在 Docker 命名卷或其他目录中，先停止旧服务，将原容器 `/data` 的完整内容（含存在的 WAL / SHM 文件）复制到这个文件夹，再设置权限并切换挂载；不要用空文件夹替代旧数据。以后升级应保持此目录不变，迁移部署目录时也要一并迁移数据文件夹。

密码直接写在 YAML 中时，如果包含 `$`，每个 `$` 要写为 `$$`，避免 Compose 将后面的内容解释为变量。不要分享已填写真实密码的配置。修改密码后须重新部署 / 重新创建容器，单纯点击「重启」不会更新容器环境变量。

通过命令行使用这一单文件配置时，在原部署目录运行：

```bash
docker compose -f compose.panel.yaml up -d --force-recreate server
```

## 配置说明

| 变量 | 用途 |
| --- | --- |
| `ADMIN_USERNAME` | 首次创建或同步密码的管理员用户名，默认 `admin`；3–40 位英文字母、数字、`_`、`.`、`-`；已有数据库时必须对应已启用的管理员，不用于重命名或提升普通成员权限 |
| `ADMIN_PASSWORD` | 管理员密码，必须自行填写，12–256 个字符；更改并重新创建容器后同步生效 |
| `FOCUSLEDGER_IMAGE` | 本地镜像标签，默认 `focusledger-server:2026.10.16-r12` |
| `FOCUSLEDGER_DATA_VOLUME` | 标准 Compose / 源码构建使用的固定外部数据卷名，默认 `focusledger-data`；新装需先创建，已有部署填写旧卷实际名称；面板版使用 `./focus-data` 文件夹，不读取此变量 |
| `SERVER_PORT` | 对外端口，默认 `8080`；容器内部始终使用 `8080` |
| `BIND_HOST` | 监听地址，默认 `0.0.0.0`；同机反向代理可设置 `127.0.0.1` |
| `RETENTION_DAYS` | 初始数据保留天数，1–365，默认 365；客户端管理页保存后以数据库中的值为准 |
| `SECURE_COOKIES` | 内网 HTTP 为 `false`，HTTPS 部署为 `true` |

公网部署请配置有效的 HTTPS 证书和反向代理，将整个站点转发到容器 8080 端口，允许至少 2 MiB 上传。客户端填写证书匹配的域名，协议选 `https`、端口通常为 `443`。如直接对外使用 8080 端口，需在服务器防火墙 / 云安全组放行所选端口。

### 网页实时刷新与反向代理

网页当前应用、设备状态与今日记录支持 SSE 实时更新；连接恢复后自动读取最新快照。每 10 秒的当前应用校验、每 30 秒的看板刷新和个人页原有定时刷新继续保留，实时连接中断时仍能更新。页面切到后台时释放连接，返回时重新连接；日期、日 / 周 / 月 / 年和设备筛选保留。

若使用 Nginx 或面板反向代理，为事件流单独设置以下规则；将 `proxy_pass` 的地址替换为实际容器映射地址。其他路径继续使用原有代理规则。

```nginx
location = /api/web/events {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 75s;
}
```

服务端每 15 秒发送心跳，并返回 `X-Accel-Buffering: no`。代理的读取超时应高于心跳间隔，CDN 或面板也须允许持续响应；若仍存在缓冲，网页会使用定时刷新并自动尝试恢复实时连接。HTTPS 继续使用有效证书和原有 Cookie 配置。

当前镜像固定单个 Uvicorn worker，可直接使用进程内通知，无需增加服务或数据卷。若自行改成多 worker / 多副本，需要接入共享通知机制；现有定时刷新仍保留。容器给持续连接预留最多 5 秒优雅退出时间。此功能需要构建并部署更新后的服务端，客户端继续使用原上传接口。

## 从旧版本升级 / 修改管理员密码

以下数据卷步骤适用于标准 `compose.yaml` 和继续使用命名卷的旧面板配置。当前面板版使用 `./focus-data` 文件夹，按上一节准备或迁移数据，升级时保持该目录不变；镜像与管理员密码的更新方式相同。

旧版已经把 `/data` 挂载到命名卷，但实际卷名由 Compose 项目名派生（通常为 `server_focus-data`）。仅更新容器本身不会清空数据；换部署目录或新建面板项目会选中另一个卷，看起来像数据丢失。标准配置改为显式指定实际卷名，并用 `external: true` 将卷的生命周期独立出来。

**替换旧配置之前**，在原部署目录查询现有容器的卷名（单文件部署时给 `docker compose` 加上 `-f compose.panel.yaml`）：

```bash
docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$(docker compose ps -a -q server)"
```

也可以在面板的原容器挂载信息中查看 `/data` 对应的数据卷。假如输出为 `server_focus-data`，在原 `.env` 中添加 `FOCUSLEDGER_DATA_VOLUME=server_focus-data`；继续使用命名卷的旧面板配置则保留 `focus-data:/data`，并将顶层 `volumes.focus-data.name` 设为 `server_focus-data`、`external` 设为 `true`。**使用查询到的真实名称，不要照抄示例或为了消除报错创建一个新空卷。** 这一步直接沿用旧卷，无需复制数据库或改权限。

如果原容器已删除，可先用 `docker volume ls` 查找旧项目的卷，并通过旧配置 / 面板信息确认。未确认前不要删除卷；只要旧卷仍在，重新挂载后就能读取其中的记录。

1. 在原部署目录按下文备份数据库，并记录上述原卷名；不要对旧版配置执行 `docker compose down -v`。
2. 将新发布包中的 TAR 上传到服务器，执行 `docker load -i FocusLedger-server-linux-amd64.tar`。
3. 更新 Compose，保持 `focus-data:/data` 挂载，并按上文将外部卷名指向旧卷。把 `image` 改为 `focusledger-server:2026.10.16-r12`；使用 `.env` 时同步修改 `FOCUSLEDGER_IMAGE`。`ADMIN_USERNAME` 填现有已启用的管理员用户名，`ADMIN_PASSWORD` 填 12–256 个字符的密码。
4. 在 1Panel 保存并重新部署原编排项目，或执行 `docker compose up -d --force-recreate server`。如果更换项目，先停止旧项目，并在新项目中使用相同的外部卷名；同一数据库只运行一个服务端实例。
5. 查看 `docker compose logs --tail=100 server`，服务健康后使用配置中的用户名和密码登录。

**r4 第一次启动会把 Compose 密码同步到对应管理员，解决旧数据库仍使用旧密码的问题。** 此后只在 Compose 密码变化时再次同步；Compose 密码不变时，在网页「账户」修改的密码可以跨重启保留。同步会注销该管理员的旧登录会话，其他用户会话、用户权限、历史记录、上传密钥和数据保留期不受影响。数据库只保存密码的加盐哈希。

空密码、短于 12 个字符或超过 256 个字符会导致启动失败，日志中明确显示 `ADMIN_PASSWORD must contain 12–256 characters`，不会悄悄继续使用旧密码。已有数据库且完全不提供管理员环境变量时，继续保留数据库中的账户密码。

## 创建用户并连接客户端

1. 用管理员账号登录网页，在「成员」创建用户。
2. 每位用户登录自己的账户，在「账户」生成上传密钥。密钥原文只显示一次，请当场复制。
3. 在 Windows 客户端填写服务器 IP / 域名、端口、协议、上传密钥和设备名称；保存通过验证后开始采集。地址框只填写 IP 或域名，不包含 `http://`、端口或路径。
4. 首页直接展示公开设备的今日使用时长、实时状态和时间线，无需登录；点击设备可查看日 / 周 / 月 / 年历史。记录默认仅供所有已登录成员查看，在看板的「成员可见」入口进入。成员在「账户」打开「公开」后，未登录访客也能查看本账户全部设备与记录；关闭后重新限制为已登录成员可见。

公开设置按账户生效，不逐台设备设置。停用账户的记录对访客和登录成员均不可见。网页和查看接口均在服务端检查可见范围，未登录请求不会返回未公开的用户名、设备、应用或使用记录；账户修改与设备上传仍仅限账户本人，成员管理仍需管理员权限。

0.2.0 起也可在 Windows 客户端的「服务端」页登录，管理员可创建、启用 / 停用用户并修改数据保留天数；普通成员可生成自己的上传密钥并自动填入连接设置。管理会话独立于上传密钥，密码不保存在客户端。缩短保留期会立即清理超期数据，新的天数保存到数据库，服务重启后仍然生效。

客户端管理页中的端口 / 证书说明不会改动 Docker 或反向代理；这些部署参数仍需在服务器侧配置。既有数据库会自动补齐管理配置表和事件摘要字段，旧账户与记录保留。

**r5 支持客户端应用名翻译同步**：保存设置后，无需产生新记录即可更新当前设备的历史名称、时间线和应用排行，离线时自动重试；原始事件和统计时长保留。设备之间的翻译独立，删除翻译后恢复各条记录上传时的名称。客户端需更新到 0.2.2，服务端需更新到 r5 或更新版本；旧 r4 镜像没有此接口。升级时自动新增映射表，已有记录保留。

**r6 新增网页交互动画**：主导航、时间范围、设备筛选、应用选中和主题菜单提供短暂过渡，连续操作保留最后一次选择，后台刷新不重复播放入场动画；遵循系统减少动态效果设置。客户端对应动画包含在 0.2.3 中，两端分别更新即可生效。

## 停止、更新与备份

```bash
docker compose logs -f --tail=100 server  # 查看日志，Ctrl+C 只退出日志查看
docker compose stop                    # 停止服务，保留容器和数据
docker compose start                   # 恢复服务
docker compose down                    # 删除容器，保留数据卷
docker compose up -d                   # 重新创建并启动
```

数据库文件为 `/data/focus.sqlite3`，应持久化整个 `/data`（包含 SQLite 的 WAL / SHM 文件）。标准配置使用外部命名卷：`focus-data` 只是 Compose 内的引用，实际名称由 `FOCUSLEDGER_DATA_VOLUME` 指定，默认 `focusledger-data`。卷名固定后，部署目录或 Compose 项目名变化不会切换到空卷；更新时保持该名称不变。面板版使用编排文件同目录的 `focus-data` 文件夹，重建容器会继续使用该目录，移动编排文件时必须一并迁移数据文件夹。

按 [Docker 的外部卷规则](https://docs.docker.com/reference/compose-file/volumes/#external)，标准配置的卷必须提前存在，Compose 不会自动创建；本版配置的 [`docker compose down -v`](https://docs.docker.com/reference/cli/docker/compose/down/) 也不会删除外部卷或面板版绑定的宿主机文件夹。显式删除数据卷或文件夹、面板的清理操作，以及旧版 Compose 配置的 `down -v` 仍可能删除数据。容器继续以 UID 10001 的普通用户运行，根文件系统只读；新命名卷会沿用镜像中 `/data` 的权限，面板版宿主机文件夹则需按上文手动设置权限。

升级时先备份，把新的镜像导入，在 `.env` 中将 `FOCUSLEDGER_IMAGE` 改成新发布的标签，再执行：

```bash
docker load -i 新版本镜像.tar
docker compose up -d --force-recreate
docker compose ps
```

保留原 `.env`，不要用示例文件覆盖。更新前暂停写入并复制数据库目录做一致性备份：

```bash
docker compose stop server
mkdir -p backups
backup_dir="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
docker compose cp server:/data/. "$backup_dir/"
docker compose start server
```

请妥善保存备份目录，并按相同的最长一年保留策略清理备份。备份失败时，也要执行 `docker compose start server` 恢复服务。

## 从源码构建与导出镜像

在项目的 `server` 目录操作，需要联网下载基础镜像与依赖。默认 `compose.yaml` 用于离线部署；源码构建需要叠加构建配置：

```bash
cp .env.example .env  # 已有 .env 时不要执行此行
nano .env
docker volume create focusledger-data  # 仅首次部署；已有部署复用 FOCUSLEDGER_DATA_VOLUME 指定的原卷
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

只构建并导出镜像，无需先配置管理员密码：

```bash
python3 build_image.py
```

Windows 安装 Docker Desktop 并切换至 Linux 容器后，也可以执行 `python build_image.py`。脚本需要 Python 3.11 或更新版本，输出到 `release/FocusLedger-server-linux-amd64.tar`，同时生成 `image-info.json` 和 `IMAGE-SHA256SUMS.txt`。

不使用 Python 脚本时，等效核心命令为：

```bash
docker build --platform linux/amd64 -t focusledger-server:2026.10.16-r12 .
mkdir -p release
docker save -o release/FocusLedger-server-linux-amd64.tar focusledger-server:2026.10.16-r12
```

本项目发布工具还需要镜像元信息和校验文件，因此重新生成完整 ZIP 时请使用 `build_image.py`。只打包服务端时，在项目根目录执行 `python tools/package_release.py --server-only`；两端都构建完成后可执行 `python tools/package_release.py` 联合打包。

## 网页主题

网页默认跟随当前电脑或手机的系统深浅色，系统切换时自动更新。每个页面（包括登录页）右上角的主题按钮可选「跟随系统 / 浅色 / 深色」；窄屏上显示为半圆图标。手动选择立即生效，保存在当前浏览器中，刷新、重新登录和再次打开后仍有效，同一浏览器的其他标签页也会同步。不跨设备或与 Windows 客户端同步。

深色模式覆盖时钟、时刻表、图表、表格和表单。浏览器禁用本地存储时，主题仍可切换，但刷新后会恢复跟随系统。

深色预览：[电脑](docs/server-dark-preview.png)、[手机](docs/server-dark-mobile-preview.png)。

## 常见问题

- **`unable to open database file`**：面板版先检查 `focus-data` 文件夹及已有数据库文件是否对 UID/GID `10001:10001` 可读写，并确认实际挂载目标是 `/data` 且可写。按面板部署章节设置权限后重新部署。
- **`bind source path does not exist`**：面板版配置要求预先创建编排文件同目录的 `focus-data` 文件夹并设置权限，详见上文。
- **`external volume ... not found`**：使用标准配置或旧命名卷配置时，新装先运行 `docker volume create focusledger-data`（自定义名称时使用对应名称）；已有部署请核对实际卷名，避免创建空卷后误以为旧数据丢失。当前面板版使用文件夹，不需要命名卷。
- **更新后记录为空**：先检查当前 `/data` 挂载的实际卷名或宿主机目录，再查找旧卷或目录；改回原挂载或停服迁移完整数据。单纯改镜像或重建容器不会清空正确挂载的数据。
- **`ADMIN_USERNAME is required` / 旧版 `First start requires ADMIN_USERNAME`**：容器没有收到合法的管理员用户名。使用本项目 `compose.yaml` 时默认用户名为 `admin`；如在 `.env` 中自定义，请检查是否含中文、空格或长度不符。修改后执行 `docker compose up -d --force-recreate server`。在面板中手动创建容器时，须在容器环境变量中同时设置 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`；仅导入镜像不会设置账号。
- **找不到镜像 / pull access denied**：先执行 `docker load`，再用 `docker image ls` 确认标签与 `.env` 中的 `FOCUSLEDGER_IMAGE` 完全一致。
- **端口被占用**：修改 `.env` 中的 `SERVER_PORT` 后执行 `docker compose up -d`，客户端端口也要同步修改。
- **网页无法打开**：检查 `docker compose ps`、日志、防火墙和云安全组；确认访问的是服务器 IP。
- **登录一直返回登录页**：内网 HTTP 部署不要启用 `SECURE_COOKIES=true`；HTTPS 部署检查反向代理和证书。
- **改环境变量后密码没变**：确认已导入并使用 r4 镜像，密码为 12–256 个字符，然后重新部署 / 执行 `docker compose up -d --force-recreate server` 更新容器环境。r3 及更早版本只在首次创建管理员时读取密码。
- **`ADMIN_USERNAME must identify an existing enabled administrator`**：配置用户名没有对应到现有已启用管理员。使用原管理员用户名；此配置不会重命名账户、提升普通成员权限或启用停用账户。
- **exec format error**：确认服务器为 x86_64；此发布包不适用于 ARM64。

## 开发与验证

r7 的设备识别改为同账户内按名称匹配（去除首尾空白），不同账户可以重名。客户端电脑识别值一致时，不同版本或不同客户端 UUID 的上传归入同一设备；另一台电脑重名时返回 HTTP 409，配套客户端 0.2.6 提示修改设备名称。用量上传、空包心跳和应用名翻译使用同一套检查。

首次运行新源码时会自动归并旧数据库中同账户同名的设备，保留使用记录、状态记录、应用名翻译和旧设备 UUID 的补传映射。旧协议没有电脑识别值，无法事后区分旧同名记录来自几台电脑；归并后的名称由第一台更新客户端绑定，其他电脑需改名。建议同步更新两端。旧客户端使用已登记 UUID 仍可上传，新 UUID 若占用已有名称则会被拒绝。

`app/` 包含接口、数据库、鉴权和网页；网页读模型在 `app/board.py`，模板在 `app/templates`，静态文件在 `app/static`。内容安全策略禁止内联脚本、内联样式和事件属性，脚本不用 `innerHTML`。协议见 [docs/API.md](docs/API.md)。

在完整项目根目录安装 `requirements-dev.txt` 后，运行 `python -m pytest server/tests`；其中 `test_upload_integration.py` 验证真实 HTTP 客户端上传，需要两端依赖。

本机演示可在项目根目录运行 `python server/tools/demo_server.py`，访问 `http://127.0.0.1:8765`，管理员为 `demo`，密码为 `preview-only-123456`。该工具使用合成数据，会重建 `.runtime/demo` 中的演示数据库，不用于正式部署。

本次发布验证与限制见根项目 `docs/VALIDATION.md`。Docker 导入命令的官方说明见 [docker image load](https://docs.docker.com/reference/cli/docker/image/load/)。
