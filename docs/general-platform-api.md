# 通用多公司个人微信 Bot 通知平台 API

## 安全模型

平台只有一套部署。数据库 API Client 的 Token 绑定一个 `company_id`，并可限制 `query`、`send`、`status` 权限及允许的 `target_code`。完整 Token 仅在创建或轮换时返回一次；列表只返回前缀。服务端以 Token 的公司授权为准，请求伪造其他 `company_slug` 返回 403。

Web“应用接入”页创建或轮换凭据后，会同时返回不含 Token 的 `integration` 元数据：配置后的 `/api/v1` 地址、公司标识、权限、用户对象范围、对象编码/名称/用途说明映射、投递模式、AI 接入说明和自检命令。生成的说明要求调用方使用精确 `target_code`，禁止根据名称、说明或 AI 猜测收件人。已有应用可由管理员读取 `GET /api/v1/api-clients/{id}/integration-guide` 重新复制说明，但无法重新读取 Token。

不得把 Token、Bot 凭据、完整微信标识写入聊天、Skill、日志或 Git。业务调用方只使用稳定 `company_slug` 和 `target_code`，不直接访问数据库，不逐个调用微信底层接口。

## 认证

```http
Authorization: Bearer <ONE_TIME_ISSUED_TOKEN>
Content-Type: application/json
```

现有 `APP_SERVICE_API_TOKEN` 与 `APP_COMPANY_SERVICE_TOKENS_JSON` 路径继续兼容；新接入必须使用 Web“应用接入”页创建的数据库 API Client。

## 查询授权公司

```http
GET /api/v1/authorized-companies
```

响应只包含当前 Token 可访问的公司及稳定 `company_id/company_slug`、显示名称和启用状态。

## 查询通知对象

```http
GET /api/v1/notification-targets?company_id=<authorized_company_id>
```

返回稳定 `target_id/target_code`、模式（`single`、`multi`、`dynamic_all`）、成员数、健康数和最近发送状态。API Client 配置了对象白名单时，只返回白名单对象。

推荐的新术语别名：

```http
GET /api/v1/companies/<company_id_or_slug>/user-objects
GET /api/v1/companies/<company_id_or_slug>/user-objects/<user_object_code>
```

别名把通知对象解释为公司业务账号，返回联系人、脱敏电话、绑定健康与 `all_available` 兼容标志。旧 `notification-targets` API 和模式字段继续可用；新 UI 不展示模式。`dynamic_all` 仍在每次预览/发送时动态展开当时全部有效 Bot，不会被转换为固定成员。完整策略见 `docs/user-object-compatibility.md`。

### 创建与识别用户对象

管理员创建新对象时，可以同时设置人类可读信息和一个面向调用方的稳定路由标识：

```http
POST /api/v1/companies/<company_id_or_slug>/user-objects

{
  "account_name": "美妆剪辑审核组",
  "routing_key": "video.beauty.review",
  "description": "AI 剪辑完成或失败时，通知美妆内容运营组"
}
```

- `account_name` 是可修改的展示名称，不参与路由。
- `routing_key` 仅在创建时可选提交，长度为 1–64，需满足 `^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$` 并在公司内唯一；重复时返回 409。它不是新的第二套 ID：服务端会将其直接固化为返回值中的权威 `user_object_code`，并在内部复用同一个 `NotificationTarget.target_code`。后续更新对象时传入 `routing_key`（包括 `null`）均返回 422。
- 未提交 `routing_key` 时，服务端继续生成 `uo_<random>` 形式的 `user_object_code`。这些随机编码与语义化编码功能完全相同，无需迁移。
- `description` 是最长 500 字符的可选、可修改用途说明，省略时默认为空字符串，也可在更新时传空字符串清空；显式传 `null` 返回 422。它用于告诉管理员和接入方“什么时候通知谁”，服务端绝不会按说明、名称或关键字匹配收件人。

创建后应将返回的 `user_object_code` 保存到调用系统的受控配置中。公开业务 API 为了兼容继续使用字段名 `target_code`；请求中填入的值就是该 `user_object_code`。

Web “应用接入”页在选择允许对象时同屏显示对象名称、`user_object_code`、用途说明与绑定/异常统计；授权前应同时核对编码与用途，不只根据显示名称选择。

## 预览

```http
POST /api/v1/notifications/preview

{
  "company_slug": "authorized-company",
  "target_code": "operations-alerts"
}
```

预览不发送，只展开当前有效成员并按 Bot 身份去重。响应仅含内部 Bot ID、脱敏标识、健康状态和可发送状态，不含 binding ID、微信完整标识或凭据。

Web “用户对象”页在对象卡片上展示名称、权威 `user_object_code` 和用途说明；未填说明时会提示管理员补充。展开详情后：

- “复制调用参数”会复制包含 `company_slug + target_code` 的 JSON，便于准确写入外部系统配置。
- “预览接收范围”调用上述预览 API，只展示对象名称/编码、用途说明、Bot 总数和健康可发送数。结果会明确标记“本次仅预览，未发送任何通知”；正式调用仍按当时的健康 Bot 重新计算。

推荐把预览作为新接入和路由配置变更时的必要验收步骤：

1. 调用用户对象列表，按外部系统中预先配置的映射选定准确 `user_object_code`，不按 `account_name` 或 `description` 猜测。
2. 使用同一个值作为 `target_code` 调用预览，核对命中 Bot 数和健康 Bot 数。
3. 预览结果为 0、对象停用或结果与预期不符时，不进入发送，记录配置错误并告警。
4. 核对通过后，发送请求必须使用同一个 `company_slug + target_code`。预览是时点快照；真正发送时服务端仍会重新检查权限、对象、成员与 Bot 健康状态。

### 外部系统显式路由示例

例如 AI 视频剪辑系统可以在受控配置中维护垂类到用户对象的显式映射：

```json
{
  "beauty": "video.beauty.review",
  "finance": "video.finance.review",
  "food": "video.food.review"
}
```

建议在创建剪辑任务时就解析并保存确定的 `user_object_code`，完成或失败后原样作为 `target_code` 使用。未知垂类必须“零发送”并进入告警/人工处理：不得默认全部对象，不得选择第一个对象，也不得让 AI 根据对象名称或说明自行猜测。

完成通知示例：

```json
{
  "company_slug": "maowang-ai",
  "target_code": "video.beauty.review",
  "title": "AI 剪辑完成",
  "body": "任务 job_9842 已完成\n垂类：美妆\n请及时审核成片",
  "media_asset_id": null,
  "idempotency_key": "video-job:job_9842:completed:v1"
}
```

## 上传可选媒体/附件

兼容接口 `POST /api/v1/video-assets` 保留。通用接口：

```http
POST /api/v1/media-assets
Content-Type: multipart/form-data
```

字段：`company_id`、`employee_id`（Bot 兼容所有者）、`file`，可选 `title/caption`。允许校验过签名的 PNG/JPEG/GIF、PDF、TXT/CSV、DOCX/XLSX、MP4/MOV/M4V/WebM。附件是一次性临时资源；目前附件批次必须只命中一个健康 Bot，防止一个临时文件被并发重复消费。多人纯文本发送不受此限制。

## 发送通知批次

```http
POST /api/v1/notifications/send

{
  "company_slug": "authorized-company",
  "target_code": "operations-alerts",
  "title": "系统告警",
  "body": "请检查生产服务",
  "media_asset_id": null,
  "idempotency_key": "source-event-stable-key"
}
```

服务端原子完成 Token、公司、对象、成员、Bot 健康和幂等校验，创建一个 Batch 与逐 Bot Delivery，再由本项目现有独立加密 Bot 凭据发送。成员按 Bot 账号去重。

- 首次创建返回 201。
- 相同公司、对象、幂等键且内容相同返回原批次和 200。
- 相同幂等键但内容不同返回 409。
- 公司、对象停用或无健康 Bot 返回明确的 409。
- `completed` 表示所有命中项均记录发送成功；`partial` 表示部分成功/失败/跳过；`failed` 表示无成功项。
- HTTP 受理、排队、mock 或 dry-run 都不能替代真实微信发送验证。

## 查询批次

```http
GET /api/v1/notification-batches/<batch_id>
GET /api/v1/notification-batches?company_id=<authorized_company_id>
```

响应包含 `total/sent/failed/skipped`，以及逐 Bot 的脱敏标识、Delivery 状态和安全失败原因。Token 不能读取其他公司批次。

## 管理 API

以下接口只允许浏览器管理员 Session 或平台维护 Token，不允许业务 API Client：

- `GET/POST/PATCH /api/v1/companies`
- `GET/POST/PATCH /api/v1/notification-targets`
- `GET/POST/PATCH/DELETE /api/v1/companies/{company}/user-objects/...`（写操作仅管理员；业务 Token 只读且电话脱敏）
- `GET /api/v1/weixin-bots`
- `GET/POST/PATCH /api/v1/api-clients`
- `GET /api/v1/api-clients/{id}/integration-guide`（只返回不含 Token 的接入说明）
- `POST /api/v1/api-clients/{id}/rotate`
- `DELETE /api/v1/api-clients/{id}`（请求体 `{ "confirm": true }`；永久删除应用与 Token，已有通知结果继续保留）
- 既有员工兼容、二维码、解绑、转交、健康检查和固定用途测试接口。

公司删除采用停用/软删除。既有 Employee、EmployeeBotBinding、Delivery、欢迎通知、测试发送和旧业务路由继续兼容。
