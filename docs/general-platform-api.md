# 通用多公司个人微信 Bot 通知平台 API

## 安全模型

平台只有一套部署。数据库 API Client 的 Token 绑定一个 `company_id`，并可限制 `query`、`send`、`status` 权限及允许的 `target_code`。完整 Token 仅在创建或轮换时返回一次；列表只返回前缀。服务端以 Token 的公司授权为准，请求伪造其他 `company_slug` 返回 403。

Web“应用接入”页创建或轮换凭据后，会同时返回不含 Token 的 `integration` 元数据：配置后的 `/api/v1` 地址、公司标识、权限、用户对象范围、投递模式、AI 接入说明和自检命令。已有应用可由管理员读取 `GET /api/v1/api-clients/{id}/integration-guide` 重新复制说明，但无法重新读取 Token。

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

别名把通知对象解释为公司业务账号，返回联系人、脱敏电话、绑定健康与 `all_available` 兼容标志。管理员创建新对象只提交 `account_name`，`user_object_code` 由服务端生成。旧 `notification-targets` API 和模式字段继续可用；新 UI 不展示模式。`dynamic_all` 仍在每次预览/发送时动态展开当时全部有效 Bot，不会被转换为固定成员。完整策略见 `docs/user-object-compatibility.md`。

## 预览

```http
POST /api/v1/notifications/preview

{
  "company_slug": "authorized-company",
  "target_code": "operations-alerts"
}
```

预览不发送，只展开当前有效成员并按 Bot 身份去重。响应仅含内部 Bot ID、脱敏标识、健康状态和可发送状态，不含 binding ID、微信完整标识或凭据。

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
