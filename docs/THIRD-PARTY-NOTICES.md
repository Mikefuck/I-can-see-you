# 第三方组件

Windows 客户端使用 Python、Qt / PySide6 / Shiboken 和 PyInstaller。服务端使用 FastAPI、Starlette、Pydantic、Uvicorn、Jinja2 和 python-multipart。

Windows 安装包使用 Inno Setup：https://jrsoftware.org/。安装向导的简体中文翻译来自 Inno Setup 6.7.3 官方源码仓库的 `Files/Languages/Unofficial/ChineseSimplified.isl`，保留了原作者信息：https://github.com/jrsoftware/issrc/blob/is-6_7_3/Files/Languages/Unofficial/ChineseSimplified.isl 。

原始项目、源代码与许可资料：

- Python：https://www.python.org/ 与 https://docs.python.org/3/license.html
- Qt / PySide6 / Shiboken：https://www.qt.io/licensing/ 与 https://code.qt.io/cgit/pyside/pyside-setup.git/
- PyInstaller：https://github.com/pyinstaller/pyinstaller
- PyWinRT 3.2.1（winrt-runtime、Windows.Media.Control / Media / Foundation / Foundation.Collections 投影，MIT）：https://github.com/pywinrt/pywinrt ，许可：https://github.com/pywinrt/pywinrt/blob/main/LICENSE
- FastAPI：https://github.com/fastapi/fastapi
- Starlette：https://github.com/Kludex/starlette
- Pydantic：https://github.com/pydantic/pydantic
- Uvicorn：https://github.com/Kludex/uvicorn
- Jinja2：https://github.com/pallets/jinja
- python-multipart：https://github.com/Kludex/python-multipart

Android 工程包含 Gradle Wrapper（Apache-2.0）：[Gradle 源码与许可](https://github.com/gradle/gradle/tree/v8.13.0)。`android/gradlew` 与 `android/gradlew.bat` 保留原始许可头，Wrapper JAR 内含 `META-INF/LICENSE`。Android 测试使用 JUnit、Robolectric 和 org.json；具体版本见 `android/app/build.gradle`，这些测试依赖不打入应用运行包。

项目原创代码使用随附 `LICENSE` 中的 GNU GPL-3.0 许可；第三方组件保留各自的版权与许可，不因项目许可而改变。Windows 文件夹版与安装版中的 Qt 动态库位于 `_internal`，PyInstaller 单文件版在运行时解包其运行库。发布二进制时需保留其附带的第三方许可资料。
