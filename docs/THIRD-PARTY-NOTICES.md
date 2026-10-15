# 第三方组件

客户端使用 Python、Qt / PySide6 / Shiboken 和 PyInstaller。服务端使用 FastAPI、Starlette、Pydantic、Uvicorn、Jinja2 和 python-multipart。

Windows 安装包使用 Inno Setup：https://jrsoftware.org/。安装向导的简体中文翻译来自 Inno Setup 6.7.3 官方源码仓库的 `Files/Languages/Unofficial/ChineseSimplified.isl`，保留了原作者信息：https://github.com/jrsoftware/issrc/blob/is-6_7_3/Files/Languages/Unofficial/ChineseSimplified.isl 。

原始项目、源代码与许可资料：

- Python：https://www.python.org/ 与 https://docs.python.org/3/license.html
- Qt / PySide6 / Shiboken：https://www.qt.io/licensing/ 与 https://code.qt.io/cgit/pyside/pyside-setup.git/
- PyInstaller：https://github.com/pyinstaller/pyinstaller
- FastAPI：https://github.com/fastapi/fastapi
- Starlette：https://github.com/Kludex/starlette
- Pydantic：https://github.com/pydantic/pydantic
- Uvicorn：https://github.com/Kludex/uvicorn
- Jinja2：https://github.com/pallets/jinja
- python-multipart：https://github.com/Kludex/python-multipart

各第三方组件保留各自的版权与许可。本项目采用动态链接的目录式 Windows 打包方式，Qt相关运行库位于 `_internal` 目录。
