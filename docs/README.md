# 文档导航

| 目标 | 文档 |
| --- | --- |
| 了解项目、查看预览与快速开始 | [项目首页](../README.md) |
| Windows 安装、设置、托盘与打包 | [Windows 客户端](../client/README.md) |
| Android 权限、后台运行、小组件与签名构建 | [Android 客户端](../android/README.md) |
| Docker 部署、升级、面板配置与备份 | [服务端教程](../server/README.md) |
| 完整功能、账户切换与缓存规则 | [使用与功能详解](USER_GUIDE.md) |
| 第三方客户端接入 | [接收协议 v1](../server/docs/API.md) |
| 了解采集内容与可见范围 | [数据与隐私说明](PRIVACY.md) |
| 配置开发环境与运行测试 | [贡献指南](../CONTRIBUTING.md) |
| 准备 GitHub 仓库及 Releases 附件 | [发布指南](RELEASING.md) |
| 查看历史验证及未覆盖的范围 | [验证记录](VALIDATION.md)、[连接审计](CONNECTION_AUDIT.md) |
| 查看项目与依赖许可 | [GNU GPL-3.0 License](../LICENSE)、[第三方组件](THIRD-PARTY-NOTICES.md) |
| 报告安全问题 | [安全说明](../SECURITY.md) |

`VALIDATION.md` 和 `CONNECTION_AUDIT.md` 中的 `.runtime/` 路径是开发时的本地日志位置，不随源码分发；历史测试结论不代表新提交自动通过验证。安装包、镜像与离线 ZIP 通过 Releases 附件分发，源码中只保留构建脚本和校验元数据。
