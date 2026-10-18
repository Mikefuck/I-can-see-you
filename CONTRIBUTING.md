# 参与开发

感谢你帮助改进 Focus Ledger。问题反馈请说明受影响的组件、版本、系统环境和复现步骤；涉及密码、上传密钥或真实使用记录时，先脱敏。安全问题请按 [安全说明](SECURITY.md) 私密报告。

## 开发环境

| 范围 | 环境 |
| --- | --- |
| Windows 客户端及完整 Python 回归 | Windows 10 / 11 x64、Python 3.12 x64 |
| 网页脚本测试 | Node.js 24，无需 npm 依赖 |
| Android | JDK 21、Android SDK Platform 36、Build Tools 36.0.0 |
| 服务端部署与镜像构建 | Docker Engine / Docker Desktop 的 Linux 容器环境、Compose 插件 |

以下命令均在项目根目录执行。完整 Python 回归包含 Windows API 和 GUI 集成，请在 Windows 上运行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

也可分别执行 `python -m pytest client/tests` 或 `python -m pytest server/tests`。用虚拟环境中的 Python 替换命令里的 `python`，避免混用依赖。GUI 测试使用隔离配置及 Qt 离屏模式。

网页交互使用 Node.js 内置测试工具：

```powershell
node --test server/tests/realtime.test.cjs server/tests/timeline.test.cjs
```

Android 可在 Android Studio 中打开 `android/`，或使用 Gradle Wrapper。配置好 `JAVA_HOME` 和 `ANDROID_HOME` 后：

```powershell
cd android
.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

Linux / macOS 使用 `sh ./gradlew` 运行同样的任务。Windows 下若中文路径导致 Robolectric 原生 SQLite 加载失败，使用 [Android 构建脚本](android/README.md#源码构建)；它提供直接运行 JUnit 的兼容方式。发布构建使用独立签名，不将密钥提交到仓库。

## 本地查看

- Windows：安装客户端依赖后执行 `python client/main.py`。
- Windows 合成界面预览：`python client/tools/preview_client.py`。
- 服务端演示：安装开发依赖后执行 `python server/tools/demo_server.py`，访问 `http://127.0.0.1:8765`。演示账户及重置行为见 [服务端说明](server/README.md#开发与验证)，只用于本机合成数据预览。
- 正式服务端和 Docker 源码构建：[服务端教程](server/README.md#从源码构建与导出镜像)。

## 修改与提交

沿用所在文件的代码风格，使用 UTF-8；换行约定见 `.editorconfig` 与 `.gitattributes`。尽量将一次改动限制在一个明确问题，协议或配置行为变化时同步更新文档和相关测试。

提交前运行与改动相关的测试，以及仓库检查：

```powershell
python tools/check_repository.py
git diff --check
```

检查工具只读取 Git 跟踪文件和未被忽略的新文件，检查本地配置、数据文件、常见密钥格式、大文件及文档链接。它不能替代人工审阅，也不扫描提交历史。

不要提交 `.env`、签名材料、数据库、真实使用记录、个人服务器地址、`.runtime/`、开发环境或构建产物。Windows EXE、APK、ZIP 与 Docker TAR 作为 Releases 附件发布。环境变量示例保留为空值或明确的示例值。

Pull Request 请说明改动后的行为、验证方式与仍然存在的限制。界面变化可提供使用合成数据的前后截图。GitHub Actions 会检查仓库内容、完整 Windows Python 回归、网页脚本、Linux 服务端镜像构建及 Android 测试、Lint 和调试包构建；不会上传发布包或使用正式签名。

## 发布

版本、签名、构建产物与校验清单的准备方式见 [发布指南](docs/RELEASING.md)。项目原创代码采用 [GNU GPL-3.0 License](LICENSE)；第三方内容保留其原有许可和署名。
