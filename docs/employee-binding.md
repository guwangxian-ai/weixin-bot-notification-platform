# 员工微信绑定

1. 管理员创建员工，系统分配稳定 UUID `employee_id`，并立即向 Hermes 已安装的官方 Weixin/iLink 登录实现请求短时二维码。
2. 页面只得到绑定会话 UUID、状态、过期时间和受 Session/RBAC 保护的二维码图片地址。官方 ticket、扫码 URL、Bot token 和完整身份都不进入 JSON、日志或审计。
3. 员工本人使用个人微信扫码并在手机确认。官方状态 `wait / scaned_but_redirect / scaned / confirmed / expired` 映射为 `pending / scanned / confirming / bound / expired`。
4. `confirmed` 返回的是独立 `ilink_bot_id + bot_token + baseurl + ilink_user_id`，不是中央 Bot 的订阅者关系。系统据此创建全局唯一 Bot 账号，再建立员工分配记录。
5. 官方 ticket 一次消费；会话还支持 `cancelled / failed / revoked`。并发确认由进程锁、会话终态和 SQLite 部分唯一索引共同约束。
6. Bot 账号、token、base URL、owner user ID 和首次入站 context token 均用 Fernet 加密；account HMAC 指纹负责唯一查找；Web 只显示掩码、绑定时间、健康状态和 `delivery_ready` 布尔值。
7. 扫码确认为 `bound` 后，用户需在新 Bot 会话发送任意一条消息。首次入站提供 iLink 发送必需的 context token 和实际 chat ID；系统加密保存后置为 `delivery_ready`，自动发送“绑定成功”并补发已等待任务。

解除绑定要求二次确认，将员工分配标为 revoked 并立即拒绝新投递；历史投递和审计保留，Bot 凭据留在账号池，可用同公司事务转交接口分配给新员工。转交不会静默覆盖，任一步失败整体回滚。

允许指令：`今日视频`、`查看文案`、`重新下载`、`换一个标题`、`视频不合适`、`已收到`、`已发布`、`退订`、`帮助`。入站必须同时匹配 Bot account 和扫码 owner；其他文本降级为帮助，不进入自由 AI 对话。旧版中央 Bot 绑定码接口仅为兼容已有记录保留，不用于新员工流程。
