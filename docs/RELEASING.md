# GitHub 与版本发布指南

源码通过 Git 仓库分发；安装包、APK、ZIP 和 Docker TAR 通过 GitHub Releases 附件分发。当前三个组件独立编号：Windows `0.3.1`、Android `0.1.6`、服务端 `2026.10.22-r18`。

## 发布前检查

先按 [README 的参与开发章节](../README.md#参与开发) 运行相关测试，再从项目根目录检查将要发布的源码：

```powershell
python tools/check_repository.py
git status --short
git diff --check
git diff
```

确认改动后提交源码，并为 Release 记录对应的标签或提交。检查 GitHub Actions 结果，保证发布附件、版本说明和对应源码一致。

## 源码中应保留什么

保留实现、测试、构建脚本、Gradle Wrapper、空的 `.env.example`、文档及使用合成数据的预览。`release/` 中的 `SHA256SUMS.txt`、镜像摘要和元数据可作为版本记录保留。

`.gitignore` 排除本地环境、配置、数据库、日志、签名材料及发布二进制。已经被 Git 跟踪的文件不会因忽略规则自动停止跟踪；需要用 `git rm --cached -- 文件路径` 移出索引并提交，这会保留本机文件。若敏感信息曾进入历史，应先轮换凭据，再单独评估历史清理，不能只删除最新文件。

## 构建与打包

Windows，在项目根目录执行，构建机需安装 Inno Setup：

```powershell
.\client\build.ps1 -Python (Resolve-Path .venv\Scripts\python.exe).Path -Package all
python tools/package_release.py --client-only --portable
```

服务端，在具备 Linux Docker 引擎的构建机执行：

```powershell
python server/build_image.py
python tools/package_release.py --server-only
```

Android，SDK 路径按实际安装位置填写：

```powershell
.\android\build.ps1 -JdkPath 'C:\Program Files\Java\jdk-21.0.10' -SdkPath 'C:\Android\Sdk'
```

Android 首次发布构建会在 `.runtime/android/` 创建本地签名。**后续正式版本必须复用并备份原签名密钥和配置，不能把它们上传到 GitHub。** CI 只构建调试 APK，不使用正式签名。

更新版本时，同步源码版本、镜像标签、Compose、环境变量示例与相关说明。重新构建之后，再生成 ZIP 和校验清单；已存在的发布包不会自动包含后续文档修改。项目 `LICENSE` 和第三方说明也应随发布文件提供，旧 EXE / APK 的内容不会因新增许可证文件自动改变。

项目原创代码采用 GNU GPL-3.0。发布 EXE、APK 或镜像时，应按 `LICENSE` 第 6 条提供相应源码；可在同一 Release 中提供对应版本的完整源码及构建脚本，并注明源码标签或提交。相应源码的范围及提供方式以许可证正文为准。

## Releases 附件

可以按组件分别发布，也可在同一 Release 中提供兼容的三端版本。标题和说明分别写明各端版本，不把 Android 或服务端版本误写为 Windows 版本。

| 本地文件 | 建议的附件名称 |
| --- | --- |
| `client/release/FocusLedger-Setup-windows-x64.exe` | 保持原名 |
| `client/release/FocusLedger.exe` | 保持原名，可选 |
| `client/release/FocusLedger-windows-x64.zip` | 保持原名，可选 |
| `client/release/SHA256SUMS.txt` | `SHA256SUMS-windows.txt` |
| `android/release/FocusLedger-android.apk` | 保持原名 |
| `android/release/SHA256SUMS.txt` | `SHA256SUMS-android.txt` |
| `server/release/FocusLedger-server-docker.zip` | 保持原名 |
| `server/release/FocusLedger-server-linux-amd64.tar` | 保持原名，可选 |
| `server/release/SHA256SUMS.txt` | `SHA256SUMS-server.txt` |
| `server/release/IMAGE-SHA256SUMS.txt`、`image-info.json` | 保持原名 |
| 根目录 `LICENSE`、`docs/THIRD-PARTY-NOTICES.md` | 保持原名 |

同一个 Release 的附件名称不能重复。三份 `SHA256SUMS.txt` 上传时分别改名即可，清单中的原始二进制文件名保持不变；本地原清单保留原名供构建工具使用。

发布前核对每份附件的 SHA-256。例如 Windows 使用 `Get-FileHash -Algorithm SHA256 文件路径`，Linux 将校验清单和对应附件放在同一目录后执行 `sha256sum -c SHA256SUMS-server.txt`。

离线部署 ZIP 只应包含必要的部署源码、镜像、配置示例、文档和许可证。GitHub 自动生成的 Source code ZIP 只包含源码，不是离线部署包。

最后在网页中检查 README 图片、文档链接、附件名称与版本说明，确认 Actions 结果及真机测试限制，然后发布。历史验证摘要与未覆盖范围见[验证记录](VALIDATION.md)。
