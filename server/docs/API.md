# 接收协议 v1

## 鉴权与连通性

所有设备接口使用请求头：

```http
Authorization: Bearer 用户在网页生成的上传密钥
```

`GET /api/v1/agent/check` 返回：

```json
{"ok":true,"account_id":1,"username":"alice","schema_version":1,"features":["app_usage","device_status"],"retention_days":365}
```

`account_id` 在当前服务器中稳定，用于客户端绑定队列；上传归属以服务端根据密钥查出的用户为准，不信任客户端提供的用户信息。

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

## 多平台扩展约定

各个平台自行采样前台应用并生成一致的分段记录。设备 ID 在安装时生成并持久保存，不能每次启动重新生成。所有客户端应遵循同样的可见状态、暂停与退出控制，以及断网队列 / 同 ID 重试规则。

添加新记录类型时先定义字段、权限和保留策略，再扩展事件模型、数据库 schema、网页展示与测试。当前接口不会保存任意文件或可执行程序，上传包只包含结构化的应用使用和设备状态 JSON。
