# 数据库

默认 SQLite：`data/notification-center.db`，启用 foreign_keys 与 WAL。正式结构由 Alembic 管理。

## 表
- `companies`：租户。
- `users`：管理员、角色和公司范围。
- `employees`：联系人资料与生命周期；联系电话只保存 Fernet 密文、用途隔离 HMAC 指纹和脱敏显示值，不保存明文。
- `binding_codes`：一次性码 HMAC、过期与消费时间。
- `weixin_bindings`：加密标识、HMAC 指纹、掩码、上下文存在性和撤销状态。
- `weixin_binding_sessions`：员工范围官方二维码会话、完整状态机、加密 ticket/扫码数据、过期与消费时间。
- `weixin_bot_accounts`：全系统唯一 iLink Bot 身份、加密 token/base URL/owner 和健康状态。
- `employee_bot_bindings`：员工与 Bot 的历史分配；SQLite 部分唯一索引确保每名员工、每个 Bot 至多一个 active 关系。
- `notification_targets`：稳定通知对象及旧 `single/multi/dynamic_all` 兼容语义；`is_user_object` 标识仅由新别名创建的业务账号对象。
- `target_bot_members`：旧 single/multi 对象按 binding 版本保存的成员历史。
- `user_object_contacts`：新用户对象到稳定联系人的关系；移除采用 inactive/removed_at 软移除，迁移 trigger 阻止跨公司关联。
- `video_assets`：一次性视频暂存的所有者、登记路径、类型、大小、SHA-256、标题文案，以及原子 `claimed_delivery_id`、`consumed_at`、`file_deleted_at` 生命周期；真实微信媒体发送成功并提交阶段状态后才删除物理文件，元数据继续保留以维持通知历史与外键完整性。
- `deliveries`：通知标题、正文、可空视频附件、状态机、幂等键、失败信息、重试、`text_sent_at` / `media_sent_at` 分阶段发送进度、内部发送租约和确认时间；历史视频投递原行保留并回填标题正文及已完成阶段。发送租约和令牌仅用于并发占用与进程中断恢复，不通过 API 返回。
- `audit_logs`：管理员/Bot 动作与目标，不保存秘密。

迁移：`.venv/bin/alembic upgrade head`。备份前建议停止写入或使用 SQLite 在线备份 API；不得只复制活动 WAL 主文件。备份目录 `backups/`，生产由运维脚本控制权限和保留期。
