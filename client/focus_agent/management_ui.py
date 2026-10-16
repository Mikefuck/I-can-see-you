from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .management import ManagementSession
from .controls import NoWheelSpinBox as QSpinBox
from .motion import MotionButton as QPushButton, MotionCheckBox as QCheckBox


class ManagementJob(QObject):
    finished = Signal(object, str)

    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        try:
            self.finished.emit(self.action(), "")
        except Exception as exc:
            self.finished.emit(None, str(exc))


class ManagementPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.session = None
        self.thread = self.job = None
        self.result = None
        self.on_success = None
        self.retention_days = 365
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 20, 48, 28)
        layout.setSpacing(14)
        heading = QLabel("服务端管理")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.endpoint = QLabel("使用「设置」页的地址登录，主地址无法连接时尝试备用地址，无需先生成上传密钥。")
        self.endpoint.setWordWrap(True)
        layout.addWidget(self.endpoint)
        login = QGridLayout()
        self.username, self.password = QLineEdit(), QLineEdit()
        self.username.setPlaceholderText("服务端用户名")
        self.username.setMaxLength(40)
        self.password.setPlaceholderText("登录密码，仅在本次登录时使用")
        self.password.setMaxLength(256)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_button, self.logout_button = QPushButton("登录"), QPushButton("退出登录")
        self.login_button.clicked.connect(self.login)
        self.logout_button.clicked.connect(self.logout)
        login.addWidget(self.username, 0, 0)
        login.addWidget(self.password, 0, 1)
        login.addWidget(self.login_button, 0, 2)
        login.addWidget(self.logout_button, 0, 3)
        layout.addLayout(login)
        self.note = QLabel("普通成员可生成自己的上传密钥；管理员还可管理用户和运行参数。")
        self.note.setWordWrap(True)
        self.note.setObjectName("hint")
        layout.addWidget(self.note)
        self.token_button = QPushButton("生成新上传密钥并填入连接设置")
        self.token_button.clicked.connect(self.rotate_token)
        layout.addWidget(self.token_button)

        self.admin = QWidget()
        admin_layout = QVBoxLayout(self.admin)
        admin_layout.setContentsMargins(0, 8, 0, 0)
        user_heading = QLabel("用户")
        user_heading.setObjectName("sectionTitle")
        admin_layout.addWidget(user_heading)
        self.users = QTableWidget(0, 4)
        self.users.setHorizontalHeaderLabels(["用户名", "角色", "状态", "操作"])
        self.users.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.users.verticalHeader().hide()
        self.users.verticalHeader().setDefaultSectionSize(42)
        self.users.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.users.setMinimumHeight(180)
        self.users.setMaximumHeight(300)
        admin_layout.addWidget(self.users)
        create = QGridLayout()
        self.new_username, self.new_password = QLineEdit(), QLineEdit()
        self.new_username.setPlaceholderText("新用户名（3–40 个英文字母、数字等）")
        self.new_username.setMaxLength(40)
        self.new_password.setPlaceholderText("初始密码（至少 12 个字符）")
        self.new_password.setMaxLength(256)
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_admin = QCheckBox("管理员")
        create_button, refresh = QPushButton("创建用户"), QPushButton("刷新")
        create_button.clicked.connect(self.create_user)
        refresh.clicked.connect(self.refresh)
        create.addWidget(self.new_username, 0, 0)
        create.addWidget(self.new_password, 0, 1)
        create.addWidget(self.new_admin, 0, 2)
        create.addWidget(create_button, 0, 3)
        create.addWidget(refresh, 1, 3)
        admin_layout.addLayout(create)
        runtime_heading = QLabel("运行参数")
        runtime_heading.setObjectName("sectionTitle")
        admin_layout.addWidget(runtime_heading)
        runtime = QGridLayout()
        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setSuffix(" 天")
        save_runtime = QPushButton("保存运行参数")
        save_runtime.clicked.connect(self.save_settings)
        runtime.addWidget(QLabel("数据保留天数"), 0, 0)
        runtime.addWidget(self.retention, 0, 1)
        runtime.addWidget(save_runtime, 0, 2)
        admin_layout.addLayout(runtime)
        self.runtime_note = QLabel()
        self.runtime_note.setWordWrap(True)
        admin_layout.addWidget(self.runtime_note)
        deploy = QLabel("对外端口和绑定地址在服务端 Docker 部署配置中修改；HTTPS 证书在反向代理中配置。"
                        "修改后请同步更新客户端连接地址。数据保留天数保存在服务端，重启后仍生效。")
        deploy.setWordWrap(True)
        deploy.setObjectName("hint")
        admin_layout.addWidget(deploy)
        layout.addWidget(self.admin)
        layout.addStretch()
        self.update_access()

    def update_access(self):
        logged = bool(self.session and self.session.user)
        self.login_button.setEnabled(not logged)
        self.username.setEnabled(not logged)
        self.password.setEnabled(not logged)
        self.logout_button.setEnabled(logged)
        self.token_button.setEnabled(logged)
        self.admin.setEnabled(logged and self.session.user.get("is_admin", False))

    def run(self, action, success):
        if self.thread is not None:
            return
        if self.window.job_thread is not None:
            self.note.setText("请等待连接验证结束后再操作服务端。")
            return
        self.result, self.on_success = None, success
        self.setEnabled(False)
        self.note.setText("正在与服务端交换数据，请稍候…")
        self.thread = QThread(self)
        self.job = ManagementJob(action)
        self.job.moveToThread(self.thread)
        self.thread.started.connect(self.job.run)
        self.job.finished.connect(self.receive)
        self.job.finished.connect(self.thread.quit)
        self.job.finished.connect(self.job.deleteLater)
        self.thread.finished.connect(self.finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def receive(self, result, error):
        self.result = result, error

    def finished(self):
        self.thread, self.job = None, None
        self.setEnabled(True)
        result, error = self.result or (None, "管理任务未完成")
        success, self.on_success = self.on_success, None
        if error:
            self.note.setText("操作失败：" + error)
        else:
            self.note.setText("操作成功。")
            try:
                success(result)
            except Exception as exc:
                self.note.setText("无法处理服务端响应：" + str(exc))
        self.update_access()

    def login(self):
        try:
            config = self.window.management_endpoint()
        except ValueError as exc:
            self.note.setText(str(exc) + "；请先在「设置」页填写连接地址。")
            return
        username, password = self.username.text().strip(), self.password.text()
        self.password.clear()
        session = ManagementSession(config)

        def action():
            user = session.login(username, password)
            return {"user": user, "overview": session.overview() if user["is_admin"] else None}

        def success(result):
            self.session = session
            self.endpoint.setText(f"已登录：{session.base_url} · {result['user']['username']}")
            if result["overview"]:
                self.show_overview(result["overview"])
            self.note.setText("登录成功，管理密码不会保存在本地。")

        self.run(action, success)

    def logout(self):
        session = self.session

        def action():
            try:
                session.request("/logout", {}, "POST")
                message = "已退出登录。"
            except RuntimeError as exc:
                message = "已清除本地管理会话；服务端退出请求失败：" + str(exc)
            finally:
                session.close()
            return {"message": message}

        def success(result):
            self.session = None
            self.users.setRowCount(0)
            self.endpoint.setText("已退出。下次登录将使用「设置」页当前的连接地址。")
            self.note.setText(result["message"])

        self.run(action, success)

    def refresh(self):
        self.run(self.session.overview, self.show_overview)

    def show_overview(self, result):
        users, settings = result["users"], result["settings"]
        self.users.setRowCount(len(users))
        for row, user in enumerate(users):
            for column, text in enumerate((user["username"], "管理员" if user["is_admin"] else "成员",
                                           "可用" if user["enabled"] else "已停用")):
                self.users.setItem(row, column, QTableWidgetItem(text))
            button = QPushButton("停用" if user["enabled"] else "重新启用")
            button.setEnabled(user["id"] != self.session.user["account_id"])
            button.clicked.connect(lambda checked=False, user=user: self.set_user_state(user))
            self.users.setCellWidget(row, 3, button)
        self.retention_days = settings["retention_days"]
        self.retention.setValue(self.retention_days)
        self.runtime_note.setText("安全 Cookie：" + ("已开启（需通过 HTTPS 登录）" if settings["secure_cookies"] else "未开启") +
                                 "。修改保留天数会立即生效；超期数据会被清理。")

    def create_user(self):
        body = {"username": self.new_username.text().strip(), "password": self.new_password.text(),
                "is_admin": self.new_admin.isChecked()}

        def action():
            self.session.request("/users", body, "POST")
            return self.session.overview()

        def success(result):
            self.new_password.clear()
            self.new_username.clear()
            self.new_admin.setChecked(False)
            self.show_overview(result)

        self.run(action, success)

    def set_user_state(self, user):
        if user["enabled"] and QMessageBox.question(self, "停用用户",
                f"停用 {user['username']} 会退出其所有会话并作废上传密钥。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        def action():
            self.session.request(f"/users/{user['id']}", {"enabled": not user["enabled"]}, "PATCH")
            return self.session.overview()

        self.run(action, self.show_overview)

    def save_settings(self):
        days = self.retention.value()
        if days < self.retention_days and QMessageBox.question(self, "缩短数据保留期",
                f"将仅保留最近 {days} 天，超期历史数据会立即清理且无法恢复。是否保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        def action():
            self.session.request("/settings", {"retention_days": days}, "PUT")
            return self.session.overview()

        self.run(action, self.show_overview)

    def rotate_token(self):
        if QMessageBox.question(self, "生成上传密钥", "新密钥会立即作废当前账户的旧密钥，其他设备也需更新。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        def success(result):
            self.window.use_management_token(self.session.base_url, result["api_key"])
            self.note.setText("新密钥已填入「设置」页，正在验证上传并保存连接。")

        self.run(lambda: self.session.request("/token", {}, "POST"), success)
