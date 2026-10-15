# 接收协议 v1

## 鉴权与连通性

所有设备接口使用请求头：

```http
Authorization: Bearer 用户在网页生成的上传密钥
```

`GET /api/v1/agent/check` 返回：

```json
{"ok":true,"account_id":1,"username":"alice","schema_version":1,"features":["app_usage","device_status","management","app_aliases"],"retention_days":365}
```

`account_id` 在当前服务器中稳定，用于客户端绑定队列；上传归属以服务端根据密钥查出的用户为准，不信任客户端提供的用户信息。

## 同步应用名翻译

`PUT /api/v1/agent/app-aliases` 使用同一上传 Bearer 密钥，正文示例：

```json
{
  "device": {
    "id": "2ad514c4-e596-4ca9-b559-a812a61a8382",
    "name": "我的工作电脑",
    "platform": "windows",
    "agent_version": "0.2.3"
  },
  "app_aliases": {"msedge.exe": "浏览器", "code": "代码编辑器"}
}
```

映射最多 500 条；进程名和显示名均为去除首尾空白后的 1–200 个字符。进程名不区分大小写，完整路径归一为文件名，可省略 `.exe`；完整进程名优先于省略后缀的名称。成功返回 `{"ok":true,"device_id":"…","app_aliases":{…}}`，其中映射为归一化后的完整快照。每次请求替换该设备的整份映射，空对象删除全部翻译，重复请求幂等。

服务端持久保存设备映射，查询时用于该设备保留期内所有历史记录、当前应用、时间线和排行。原始事件、进程名、时长和去重摘要不改写，离线旧记录补传时也使用最新映射显示；删除翻译后显示各条记录上传时的名称。此操作不影响其他设备，无需上传新使用记录；未知设备会按上传规则登记，属于其他账户的设备返回 409，错误密钥返回 401，无效映射返回 422。

客户端保存设置后立即后台同步，失败按上传退避策略重试；映射保存在本机配置中，重启后会再次同步。旧版服务端返回 404 / 405 时，客户端继续上传使用记录，并提示升级服务端。

## 上传包

`POST /api/v1/usage/batches`，`Content-Type: application/json`。单包最多500条、总请求不超过2MiB。空 `events` 列表可用作设备心跳。

```json
{
  "schema_version": 1,
  "device": {
    "id": "2ad514c4-e596-4ca9-b559-a812a61a8382",
    "name": "我的工作电脑",
    "platform": "windows",
    "agent_version": "0.1.0"
  },
  "events": [
    {
      "id": "ef4657c4-a932-4644-9633-ea6892f6ac30",
      "kind": "app_usage",
      "app_name": "Microsoft Edge",
      "process_name": "msedge.exe",
      "started_at": "2026-10-09T05:00:00+00:00",
      "ended_at": "2026-10-09T05:00:30+00:00",
      "duration_seconds": 30
    }
  ]
}
```

设备和事件 ID 须为 UUID。`app_usage` 的时间必须包含时区，持续时间须与起止时间匹配且大于0、最多600秒；`device_status` 使用带时区的 `occurred_at`。`platform` 支持小写字母、数字、下划线与连字符，方便其他平台接入；不要求来自 Windows。当前支持 `app_usage` 和 `device_status` 两种事件，不接受未定义的额外字段。

`device_status` 用于记录电池状态以及关机、休眠、恢复等生命周期节点：

```json
{
  "id": "04e2e3d3-e1e6-4fd6-bc1a-8dc50d9f4f9e",
  "kind": "device_status",
  "occurred_at": "2026-10-12T05:00:00+00:00",
  "reason": "suspend",
  "battery_percent": 82,
  "charging": false,
  "ac_online": false,
  "battery_life_seconds": 14400
}
```

`reason` 可为 `periodic`、`startup`、`shutdown`、`suspend` 或 `resume`。状态事件与应用使用记录使用同一批次、同一重试和去重规则，但服务端单独存储，不会出现在应用使用排行中。

客户端在生成记录时保存固定事件 ID，重试使用同一个 ID。服务端在一个事务里完成整包入库，同一用户 / 设备 / 事件 ID 不重复累计。

响应示例：

```json
{
  "acknowledged_ids": ["ef4657c4-a932-4644-9633-ea6892f6ac30"],
  "inserted": 1,
  "duplicates": 0,
  "expired": 0,
  "server_time": "2026-10-09T05:00:31+00:00"
}
```

`acknowledged_ids` 包括成功插入、已存在和超期丢弃的记录，客户端只删除 / 标记服务端确认的记录。跨越保留期边界的记录仅保存边界之后的部分。

| 状态码 | 含义 |
| --- | --- |
| 200 | 已接受 / 重复已确认 / 超期已丢弃 |
| 401 | 上传密钥错误、被重置或账户停用 |
| 409 | 设备归属于另一账户或记录 ID 冲突，整包回滚 |
| 413 | 请求大于2MiB |
| 422 | 数据格式无效、持续时间不符、时间不含时区、设备时钟超前超过5分钟 |

`GET /healthz` 不需要鉴权，仅用于容器健康检查，不返回账户或设备信息。

## 客户端管理接口（0.2.0）

管理接口前缀为 `/api/v1/management`，使用独立的登录 Cookie 会话，**上传 Bearer 密钥不授予管理权限**。所有请求 / 响应使用 JSON。登录后的修改操作必须携带登录返回的 `X-CSRF-Token`；会话有效期 12 小时。公网使用 HTTPS。

| 方法及路径 | 权限与参数 |
| --- | --- |
| `POST /login` | 请求头 `X-FocusLedger-Client: desktop`，正文 `username`、`password`；返回 `account_id`、`username`、`is_admin`、`csrf`，设置 HttpOnly 登录 Cookie。 |
| `POST /logout` | 当前登录账户，注销当前会话。 |
| `GET /users` | 管理员，返回 `users` 列表，仅含 `id`、`username`、`is_admin`、`enabled`。 |
| `POST /users` | 管理员，正文 `username`、`password`、`is_admin`；新用户默认不公开。 |
| `PATCH /users/{id}` | 管理员，正文 `enabled`；不能停用自己。停用会注销目标用户全部会话并作废上传密钥。 |
| `GET /settings` | 管理员，返回 `retention_days`、只读的 `secure_cookies`、协议版本和管理版本。 |
| `PUT /settings` | 管理员，正文 `retention_days`（整数 1–365）；持久化并立即清理超期数据，返回生效配置。 |
| `POST /token` | 当前登录账户，返回新的 `api_key`、`account_id`、`username`，旧上传密钥立即失效。 |

未登录返回 401；权限不足或 CSRF 不符返回 403；用户名冲突返回 409；字段无效返回 422。端口映射、证书和 Docker 重启不在此 API 的修改范围内。

## 多平台扩展约定

各个平台自行采样前台应用并生成一致的分段记录。设备 ID 在安装时生成并持久保存，不能每次启动重新生成。所有客户端应遵循同样的可见状态、暂停与退出控制，以及断网队列 / 同 ID 重试规则。

添加新记录类型时先定义字段、权限和保留策略，再扩展事件模型、数据库 schema、网页展示与测试。当前接口不会保存任意文件或可执行程序，上传包只包含结构化的应用使用和设备状态 JSON。
