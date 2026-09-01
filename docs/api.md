# API

OpenAPI：`/api/openapi.json`；Swagger UI：`/api/docs`。正式地址前加应用子路径。

## 认证
- Web：`POST /api/v1/auth/login`，签名 HttpOnly Session Cookie；修改请求传 `X-CSRF-Token`。
- 业务 Skill：`Authorization: Bearer TENANT_TOKEN`；令牌必须在 `APP_COMPANY_SERVICE_TOKENS_JSON` 中只对应一个公司。
- 平台维护兼容令牌：`APP_SERVICE_API_TOKEN` 拥有平台管理权限，仅本维护 Profile 使用，不得发给业务 Profile。
- Bot worker：`X-Bot-Secret` 仅用于 `/api/v1/bot/inbound`。

业务令牌只允许 `GET /employees`、`GET /employees/{id}`、`GET/POST /video-assets`、`GET /deliveries`、`POST /deliveries` 和 `GET /deliveries/{id}`。员工增删改、绑定会话/二维码、解绑/转交、下载链接签发、投递重试/取消、Bot 健康、审计和用户管理均返回 403。公司范围由令牌决定，不能通过请求参数扩大；员工响应不包含绑定会话或二维码元数据。

## 主要资源
- 员工：`GET/POST /employees`、`GET/PATCH/DELETE /employees/{id}`。
- 绑定会话：`POST /employees/{id}/binding-sessions`、`GET /binding-sessions/{id}`、`POST /binding-sessions/{id}/poll|cancel`、`GET /binding-sessions/{id}/qr.png`。
- 绑定管理：`POST /employees/{id}/unbind`（请求体 `confirm=true`）、`POST /binding-transfers`、`POST /bot/inbound`。旧 `binding-code` 只做兼容。
- 一次性视频暂存（兼容路由）：`GET/POST /video-assets`；历史下载签发与下载路由继续保留兼容，但新通知不使用下载链接。
- 通知投递：`GET/POST /deliveries`、`GET /deliveries/{id}`、`POST /deliveries/{id}/retry|cancel`。
- Bot：`GET /bot/health`。
- 审计：`GET /audit-logs`。

创建通知必须提供 `company_id`、稳定 `employee_id` 和公司范围唯一 `idempotency_key`，并至少提供非空 `title`、`body` 或可选附件 `video_asset_id` 之一。附件必须属于同公司、同员工。重复请求返回同一任务（200），首次创建返回 201；响应包含标题、正文、可选附件、状态、失败码和失败原因。

视频上传只接受签名与扩展名一致的 MP4/M4V/MOV/WebM，按 1 MiB 分块写入并同时受 `APP_UPLOAD_MAX_BYTES` 与 `APP_NATIVE_VIDEO_MAX_BYTES` 限制；缺少 `Content-Length`、伪造类型或超限请求会被拒绝，失败不会留下记录或文件。视频仅可成功投递一次：真实微信发送成功后立即删除物理文件，只保留通知、附件元数据和审计记录；失败、待互动和 dry-run 不删除文件。

完整字段与响应以运行时 OpenAPI 为准；API 不返回密码哈希、官方 QR ticket/扫码 URL、Bot token、加密字段、资产物理路径或完整微信标识。二维码 PNG 需登录且 `Cache-Control: no-store`。
