# Windows 客户端 · Focus Ledger

本目录包含 Windows 客户端源码、界面、采集与上传逻辑、测试、预览工具和发布包。服务端单独部署在项目的 `server` 目录。

## 直接使用

源码目录中已打包的程序为 `dist/FocusLedger/FocusLedger.exe`，压缩包位于 `release/FocusLedger-windows-x64.zip`。解压后运行 `FocusLedger/FocusLedger.exe`；请保留并复制整个 `FocusLedger` 文件夹，无需另装 Python。

1. 在服务端网页创建用户，并在「账户与密钥」生成该用户的上传密钥。
2. 在客户端填写服务器 IP / 域名、端口、HTTP / HTTPS、上传密钥和设备名称。
3. 保存设置并通过连接验证后，点击「开始采集」。
4. 需要开机启动时勾选「登录 Windows 后自动启动」，然后保存。关闭窗口后程序留在系统托盘，右键托盘可以暂停、上传或退出。

`FocusLedger.exe --show` 强制显示窗口，`--silent` 强制托盘启动。程序已在运行（包括静默在托盘中）时再次运行它，会打开已有实例的主窗口。移动程序文件夹后，从新位置运行一次即可自动更新开机启动路径；「自动启动」复选框显示 Windows 的实际状态，在任务管理器中被关闭时会提示，重新勾选保存即可恢复。

配置、日志与 SQLite 队列保存在 `%LOCALAPPDATA%\FocusLedger`，上传密钥使用当前 Windows 账户的 DPAPI 加密；若密钥无法解密（例如换了 Windows 账户），其他设置保留，只需重新填写密钥。只记录前台应用名称、进程名和使用时间；在设置允许时，也记录电池电量、充电状态以及关机 / 睡眠 / 唤醒节点。不采集窗口标题、截图、键盘输入或文件内容。

### 电源与电池

- 关机 / 注销和睡眠 / 休眠通知由一个从不显示的系统窗口接收，静默启动时同样有效。事件发生时先把当前使用片段和状态写入本地队列，再限时上传：关机约3秒、睡眠约1.5秒（Windows 只给约2秒）。程序不会阻止关机或睡眠，来不及上传的记录下次联网时补传。
- 唤醒后记录一次恢复节点，并在后台补传，不阻塞界面。
- 电池状态按设置的间隔记录，插拔电源时立即补记；台式机无电池时电量为空。取消「采集并上传电池状态」后，关机 / 睡眠节点中也不包含电池信息。

### 应用名翻译

按进程名匹配，不区分大小写，可写 `chrome.exe`、`chrome` 或粘贴完整路径。「添加翻译」会预填最近一个还没有翻译的应用；双击最近记录中的应用行可直接为它添加或修改翻译。进程名重复时保存会提示。商店（UWP）应用按实际应用进程（如 `CalculatorApp.exe`）匹配。

## 源码运行与打包

推荐 Windows 10 / 11 x64、Python 3.12 x64。以下命令在本目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
.\build.ps1 -Python (Resolve-Path .venv\Scripts\python.exe).Path
```

打包输出为 `dist/FocusLedger`，中间文件位于 `build`。在项目根目录执行 `python tools/package_release.py` 可生成本目录 `release` 下的发布包和 SHA-256 校验文件。

## 开发文件

- `focus_agent/`：客户端实现。
- `tests/`：采集、缓存、配置与 GUI 测试。
- `tools/preview_client.py`：使用合成记录生成预览，不采集桌面或发送网络请求。
- `docs/`：客户端预览图片。

在项目根目录安装 `requirements-dev.txt` 后，执行 `python -m pytest client/tests`。预览命令为 `python client/tools/preview_client.py`。
