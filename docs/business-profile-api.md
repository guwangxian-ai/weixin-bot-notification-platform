# 业务 Profile 调用边界

> 新接入请优先阅读 `docs/general-platform-api.md`，使用数据库 API Client 与 `target_code` 批次接口。本页后半部分保留旧 `employee_id` API，作为现有 Profile 的兼容说明。

## 适用对象

本说明供获授权的业务 Profile、Agent 和其他业务系统使用。业务 Profile 是调用方，不是平台管理员。

## 凭据与地址

平台维护者通过 Web“应用接入”页为每个 Profile 创建独立数据库 API Client。Token 绑定公司、`query/send/status` 权限及可选 `target_code` 白名单；完整值只在创建或轮换时显示一次，数据库只存安全摘要和前缀。真实值只放在调用 Profile 的秘密环境，不写入 Skill、聊天、日志或 Git。旧环境变量公司 Token 继续兼容，但不再用于新接入。

调用方配置：

- `EMPLOYEE_VIDEO_NOTIFICATION_API`：推荐同机内部地址 `http://127.0.0.1:8091/api/v1`；跨机时使用现有 HTTPS 前缀后加 `/api/v1`。
- `EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN`：只绑定一个 `company_id` 的业务令牌。

平台创建接入后提供两个独立复制动作：“复制 Token”只用于写入调用应用的秘密环境；“复制 AI 接入说明”只包含环境变量名和调用契约，不包含真实 Token。不要把两者合并后发送到 AI 对话。

不得请求或使用平台维护凭据 `APP_SERVICE_API_TOKEN`。本仓库不生成、提交或展示任何真实令牌。

## 允许操作

新接口：

| 能力 | 方法与路径 | 约束 |
|---|---|---|
| 查询授权公司 | `GET /authorized-companies` | 只返回 Token 公司 |
| 查询通知对象 | `GET /notification-targets?company_id=<company>` | 受 target_code 白名单限制 |
| 发送预览 | `POST /notifications/preview` | 不发送，只返回脱敏 Bot 摘要 |
| 批次发送 | `POST /notifications/send` | `target_code` + `idempotency_key`；逐 Bot 去重 |
| 查询批次 | `GET /notification-batches/{id}` | 总计与逐 Bot 脱敏结果 |
| 暂存媒体 | `POST /media-assets` | 单健康 Bot 批次的一次性图片/文件/视频 |

以下为旧员工兼容接口：

| 能力 | 方法与路径 | 约束 |
|---|---|---|
| 查询员工列表 | `GET /employees?company_id=<company>` | 令牌公司必须匹配 |
| 查询员工详情 | `GET /employees/{employee_id}` | 只用稳定 ID，不按姓名猜测 |
| 查询临时视频元数据 | `GET /video-assets?company_id=<company>` | 兼容路由；不是长期资产库，只返回令牌公司 |
| 暂存一次性视频附件 | `POST /video-assets` multipart | `company_id`、`employee_id`、`file`；员工必须同公司；仅 MP4/M4V/MOV/WebM 且不得超过微信直接发送上限 |
| 查询通知列表 | `GET /deliveries?company_id=<company>` | 只返回令牌公司 |
| 创建通知 | `POST /deliveries` JSON | 必须有可重放幂等键，正文/标题/附件至少一个 |
| 查询投递状态 | `GET /deliveries/{delivery_id}` | 任务必须属于令牌公司 |

创建通知 JSON：

```json
{
  "company_id": "AUTHORIZED_COMPANY",
  "employee_id": "STABLE_EMPLOYEE_UUID",
  "title": "通知标题",
  "body": "通知正文",
  "video_asset_id": null,
  "idempotency_key": "CALLER_STABLE_EVENT_KEY"
}
```

`video_asset_id` 可省略；提供时必须与 `company_id` 和 `employee_id` 同时匹配。它是一次性暂存引用，不是可复用资产：真实微信发送成功后平台立即删除视频文件，仅保留通知、附件元数据和审计记录；发送失败或等待首次互动时文件保留。首次创建返回 201，重复幂等请求返回原任务和 200。

## 明确禁止

业务令牌不能：

- 创建、修改、停用、删除员工；
- 创建/轮询/取消绑定会话或读取二维码；
- 解绑、转交或修改微信 Bot；
- 创建用户或修改 RBAC；
- 重试、取消投递或签发下载链接；
- 读取 Bot 健康、审计日志、平台配置、秘密或完整微信标识；
- 访问其他公司的任何资源。

后端对这些操作返回 403。业务 Profile 不得通过浏览器 Session、共享维护令牌、直接数据库访问或调用未列出的接口绕过边界。

## 推荐 Skill

复制/安装时使用仓库内 `skill/employee-video-notification/`，不要扩展其操作列表。客户端支持：

```text
list_employees
get_employee_profile
upload_video
create_notification
create_video_delivery
get_delivery_status
```

业务调用必须透传 API 的实际状态和 `failure_code` / `failure_message`：

- `sent`：平台记录官方发送成功，不等于员工已读；
- `simulated`：仅在隔离 mock/dry-run 中完成模拟，未发送微信，不计入成功发送；
- `confirmed`：员工已回复确认；
- `waiting_interaction`：等待员工首次互动，不能声称已发送；
- `failed`：保留原任务并交由平台维护者处理；业务 Profile 不自行重试或换幂等键制造重复通知。

## 开通流程

1. 业务负责人给出公司 ID、调用 Profile 和最小用途；平台维护者核对租户授权。
2. 平台维护者在“应用接入”页创建独立客户端，按最小权限和 target_code 签发一次性 Token，并直接保存到调用 Profile 的受控秘密存储；不在聊天中展示。
3. 重启应用服务前先做发布备份；Bot worker 只在原本 active 时重启。随后用非生产员工/通知验证允许操作和跨公司/管理接口 403。
4. 记录客户端负责人和轮换计划，但不记录 Token 值。轮换后旧 Token 立即失效；删除应用后其 Token 立即失效，且接入记录不保留，无需修改环境文件或重启服务。
