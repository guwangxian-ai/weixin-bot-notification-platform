# 故障排查

## 401/403
确认登录 Cookie、CSRF header、角色与 `company_id`。Skill 检查服务令牌；Bot 入站检查专属 Bot secret。不要把令牌复制到浏览器或日志。

## waiting_interaction
员工尚无可用 context token。让已绑定员工向专属通知 Bot 发送“今日视频”或其他允许指令；系统会刷新上下文并补发原任务。

## 微信发送失败
查看投递 `failure_code/failure_message` 和 Bot service journal。`errcode=-14` 通常表示会话过期，需要专属 Bot 重新扫码。若提示 token 锁，确认没有第二个轮询器使用同一专属 token；不要停止其他 Profile 的管理 Bot。

## UI 404 或资源路径错误
确认 Vite `base: './'`、`web/dist` 存在、Nginx proxy_pass 末尾斜杠和 `X-Forwarded-Prefix`。先检查内部 8091，再检查 HTTPS 子路径。

## 数据库 locked
确认只有本项目访问数据库、磁盘空间正常且没有长期事务。不要删除 `-wal/-shm` 文件。备份后再检查 journal。

## Nginx 失败
立即保留旧配置，不 reload。对比部署时创建的受限备份，修复后再次执行 `nginx -t`。
