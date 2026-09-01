# 运维

## 日常检查
- `systemctl status weixin-bot-notification-platform`
- `systemctl status weixin-bot-notification-platform-bot`
- `journalctl -u weixin-bot-notification-platform --since today`
- `curl http://127.0.0.1:8091/api/v1/health`
- 管理端检查 Bot 状态、失败任务、waiting_interaction 和审计日志。

## 重试与取消
仅 `failed` 或 `waiting_interaction` 可重试；重试复用同一任务并增加 `retry_count`。确认任务不可取消。不得通过创建新幂等键掩盖失败。

## 员工生命周期
禁用、离职、软删除员工均不得新建投递。页面在停用/离职时提示是否随后解绑；解绑要求二次确认并释放 Bot，转交必须用单一事务 API。微信票据、凭据和完整标识不得从 journal 或普通日志导出。

## 备份与恢复
每日备份 SQLite（使用 online backup API 获取一致快照）、上传资产和环境文件的密文备份；目录 0700、文件 0600。发布备份还包含 Git bundle/source、systemd/tmpfiles 和 Nginx 配置。恢复先在隔离目录校验 SHA-256、`git bundle verify`、SQLite `integrity_check` 和 Alembic 版本，再停止两个项目服务并切换；不得只复制活动 WAL 主文件。

## 密钥轮换
Session/服务/Bot webhook/HMAC/加密密钥分离。Fernet 与 HMAC 轮换需要数据迁移，不能直接替换导致历史绑定不可读。每员工 Bot token 存在数据库密文中，不写环境文件。
