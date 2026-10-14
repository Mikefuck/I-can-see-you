# Linux Docker 服务端 · Focus Ledger

本目录包含服务端接口、数据库、网页、Docker 部署配置、测试、演示工具和发布包。Windows 客户端位于项目的 `client` 目录。

## 部署

将本目录复制到 Linux 服务器，或解压 `release/FocusLedger-server-docker.zip` 后进入其中的 `server` 目录。需要 Docker Engine 和 Compose 插件：

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f server
```

在 `.env` 中填写 `ADMIN_USERNAME` 和至少 12 个字符的 `ADMIN_PASSWORD`。默认网页端口为 `8080`，可用 `SERVER_PORT` 修改；`RETENTION_DAYS` 支持 1–365 天。管理员仅在首次创建数据库时初始化，已有数据库的密码不会被环境变量覆盖。

1. 打开 `http://服务器IP:8080`，使用管理员账户登录。
2. 在「成员」创建用户。
3. 用户登录自己的账户，在「账户」生成上传密钥，填写到对应客户端中。密钥原文只显示一次。
4. 记录默认只有本人能看到。成员在「账户」页打开「公开」后，其他成员才能在总览和成员记录里看到对方的设备与使用情况；随时可以关闭。管理员同样只能看到已公开的记录。

公网部署请配置 HTTPS 反向代理并设置 `SECURE_COOKIES=true`；内网 HTTP 使用时保持 `SECURE_COOKIES=false`。客户端填写证书匹配的域名和反向代理端口。反向代理转发到容器的 8080 端口，上传包限制至少 2 MiB。

数据库保存在 Docker 命名卷 `focus-data`。`docker compose down` 保留数据，**`docker compose down -v` 会删除数据**。

## 开发文件

- `app/`：接口、数据库、鉴权与网页。`app/board.py` 是网页的读模型（谁能被看到、设备当前状态、使用时段与分箱）；模板在 `app/templates`，样式与脚本在 `app/static`。页面由模板给出骨架，时刻表和图表由 `app/static/app.js` 按浏览器时区绘制，数据来自 `/api/web/*`（需要登录会话）。
- 网页的内容安全策略是 `default-src 'self'`：模板和脚本里不能写内联 `<style>`、`style=`、事件属性或内联脚本，脚本也不使用 `innerHTML`，测试会检查这些约束。
- `requirements.txt`：服务端运行依赖。
- `Dockerfile`、`compose.yaml`、`.env.example`：部署配置。
- `tests/`：服务端测试和真实 HTTP 客户端上传联调测试。
- `tools/demo_server.py`：使用合成记录的本机演示服务。
- `docs/API.md`：客户端接收协议；同目录还保存网页预览图片。
- `release/`：服务端部署包与 `SHA256SUMS.txt`。

在项目根目录安装 `requirements-dev.txt` 后，执行 `python -m pytest server/tests`。联调测试需要两端依赖。

本机演示命令为 `python server/tools/demo_server.py`，访问 `http://127.0.0.1:8765`，管理员账户为 `demo`，密码为 `preview-only-123456`；另有成员 `alice`、`bob`（已公开）和 `carol`（未公开，演示管理员也看不到），密码相同。每次启动都会按当前时间重建演示数据库（位于项目根目录 `.runtime/demo`），其中几台设备处于使用中、空闲、休眠、关机等各种状态，并且「使用中」的设备会持续上报，可以直接看到总览自动刷新。

在项目根目录执行 `python tools/package_release.py` 可重新生成两端发布包，服务端压缩包只包含部署所需文件，不包含本地数据、环境密钥、测试或已有发布包。
