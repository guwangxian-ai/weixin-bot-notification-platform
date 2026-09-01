# 故障排查

## 401/403
确认登录 Cookie、CSRF header、角色与 `company_id`。Skill 检查服务令牌；Bot 入站检查专属 Bot secret。不要把令牌复制到浏览器或日志。

## waiting_interaction
新绑定尚未获得 iLink context token。请在微信中打开刚绑定的独立 Bot 会话并发送任意消息；平台会加密保存会话上下文、自动补发绑定成功和其他等待任务。若日志在没有 context 时显示 `ret=-2 / rate limited`，它很可能是 Hermes 将 iLink `prepare failed` 误分类，不要机械重试。

## 微信发送失败
查看投递 `failure_code/failure_message` 和 Bot service journal。`errcode=-14` 通常表示会话过期，需要专属 Bot 重新扫码。若提示 token 锁，确认没有第二个轮询器使用同一专属 token；不要停止其他 Profile 的管理 Bot。

## UI 404 或资源路径错误
确认 Vite `base: './'`、`web/dist` 存在、Nginx proxy_pass 末尾斜杠和 `X-Forwarded-Prefix`。先检查内部 8091，再检查 HTTPS 子路径。

## 数据库 locked
确认只有本项目访问数据库、磁盘空间正常且没有长期事务。不要删除 `-wal/-shm` 文件。备份后再检查 journal。

## Nginx 失败
立即保留旧配置，不 reload。对比部署时创建的受限备份，修复后再次执行 `nginx -t`。
