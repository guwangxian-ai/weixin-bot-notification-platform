---
name: employee-video-notification
description: "Use when sending company-scoped Weixin Bot notifications."
version: 3.0.0
metadata:
  hermes:
    tags: [weixin, bot, employee, notification, delivery]
---

# 通用多公司微信 Bot 通知平台

供普通业务 Profile 调用公司级授权 REST API：查询授权公司与通知对象、预览脱敏 Bot 命中、按稳定 `target_code` 发送文字或可选一次性媒体/附件、查询批次和逐 Bot 结果。禁止读取微信 token、context token、完整微信标识或直接访问数据库。

## 前置条件
- `EMPLOYEE_VIDEO_NOTIFICATION_API`：通知中心 `/api/v1` 地址。
- `EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN`：通知中心签发的服务账号令牌。

令牌必须是平台 API 管理创建且只对应一个 `company_id` 的数据库 API Client Token，可限制 `query/send/status` 和 `target_code`。完整 Token 仅签发或轮换时出现一次；不得使用或索取平台维护令牌。

## 操作
使用 `scripts/client.py`：
- `authorized_companies`
- `list_targets --company-id COMPANY_ID`
- `preview --company-slug COMPANY --target-code CODE`
- `send --company-slug COMPANY --target-code CODE --title TITLE --body BODY --idempotency-key KEY [--media-asset-id ID]`
- `get_batch --batch-id BATCH_ID`
- `upload_media --company-id COMPANY_ID --employee-id COMPAT_OWNER_ID --file PATH`

以下操作是旧 Profile 兼容入口，不用于新接入：
- `list_employees --company-id COMPANY_ID`
- `get_employee_profile --employee-id EMPLOYEE_ID`
- `upload_video --company-id COMPANY_ID --employee-id EMPLOYEE_ID --file PATH [--title TITLE] [--caption CAPTION]`
- `create_notification --company-id COMPANY_ID --employee-id EMPLOYEE_ID --title TITLE --body BODY [--video-asset-id ASSET_ID] --idempotency-key KEY`
- `create_video_delivery --company-id COMPANY_ID --employee-id EMPLOYEE_ID --video-asset-id ASSET_ID --idempotency-key KEY`
- `get_delivery_status --delivery-id DELIVERY_ID`

## 强制规则
1. 新调用只用稳定 `company_slug + target_code` 解析通知对象；不按姓名模糊匹配，不自行展开成员或拼接微信请求。旧兼容调用仍只用 `employee_id`。
2. 每次创建通知批次必须提供可重放的 `idempotency_key`；同键不同内容是冲突，不能换键制造重复通知。
3. `sent` 只表示平台发送成功；只有 `confirmed` 表示员工回复“已收到”。
4. `partial` 必须逐 Bot 检查 `sent/failed/skipped`；`waiting_interaction` 不得丢弃或重复新建任务。
5. mock/dry-run 不代表真实微信验证成功。
6. 创建通知至少提供非空标题、正文或 `media_asset_id`。附件是一次性临时资源，目前仅允许命中一个健康 Bot；多人对象使用纯文本批次。
7. `failed`、`waiting_interaction`、未绑定、停用、解绑或凭据失效必须把 API 返回的 `failure_code` / `failure_message` 交给调用者，不得宣称已发送。
8. 不得调用公司、通知对象、API Client、员工增删改、绑定/二维码、解绑/转交、重试/取消、用户、Bot 健康、审计、配置或下载链接签发接口；这些是平台维护操作。
9. 上传视频后应立即用返回的 `video_asset_id` 创建通知。它不是长期资产：真实微信发送成功后文件会被删除且不能再次投递；失败、待互动和 dry-run 不会触发删除。
