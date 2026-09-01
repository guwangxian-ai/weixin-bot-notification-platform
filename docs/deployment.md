# 部署

本文档给出一套通用 Linux + systemd + Nginx 部署示例。请先根据服务器的用户、目录、域名和 Hermes 安装位置调整 `deploy/` 中的文件。

## 示例约定

- 应用目录：`/opt/weixin-bot-notification-platform`
- 运行用户：`weixinbot`
- 环境文件：`/etc/weixin-bot-notification-platform.env`（`root:root 0600`）
- API 服务：`weixin-bot-notification-platform.service`
- Bot worker：`weixin-bot-notification-platform-bot.service`
- 内部监听：`127.0.0.1:8091`
- Nginx 子路径：`/weixin-bot-notification-platform/`

## 准备应用

```bash
sudo useradd --system --home /opt/weixin-bot-notification-platform --shell /usr/sbin/nologin weixinbot
sudo install -d -o weixinbot -g weixinbot -m 0750 /opt/weixin-bot-notification-platform
```

将仓库放入应用目录，并使用运行用户安装依赖、构建前端：

```bash
uv sync --frozen --dev
npm --prefix web ci
npm --prefix web run build
```

从 `.env.example` 创建生产环境文件，修改公网 URL、数据库、所有密钥、管理员密码、可信代理和微信投递模式。不要在 Shell 历史、Git 或可读日志中留下真实凭据。

## 安装服务

```bash
sudo install -o root -g root -m 0644 deploy/weixin-bot-notification-platform.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/weixin-bot-notification-platform-bot.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/weixin-bot-notification-platform.conf /etc/tmpfiles.d/
sudo systemd-tmpfiles --create /etc/tmpfiles.d/weixin-bot-notification-platform.conf
sudo systemctl daemon-reload
sudo systemctl enable --now weixin-bot-notification-platform.service
```

只有在 `APP_DELIVERY_MODE=weixin`、Hermes Weixin/iLink 运行时可用且存在独立 Bot 凭据时，才启用 worker：

```bash
sudo systemctl enable --now weixin-bot-notification-platform-bot.service
```

每个 Bot token 在同一台主机上只能有一个消费者。不得将其他项目的管理 Bot 凭据复制到本平台。

## Nginx

将 `deploy/nginx-location.conf` 放入已配置 TLS 的 `server` 块，根据需要调整子路径和上传限制：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

生产环境不应直接对公网暴露 Uvicorn 端口。

## 发布流程

1. 保存当前源码版本，并用 SQLite online backup API 创建一致性数据库备份。
2. 备份上传文件、环境文件、systemd unit 和 Nginx 配置，记录 SHA-256。
3. 执行 `uv sync --frozen --dev` 和 `npm --prefix web ci`。
4. 执行 `scripts/verify-release.sh`。
5. 执行 `.venv/bin/alembic upgrade head` 和 `npm --prefix web run build`。
6. 重启 API 服务；Bot worker 只在发布前已启用或明确需要真实投递时重启。
7. 只有在 Nginx 配置变化且 `nginx -t` 通过后才 reload。
8. 检查内部健康接口、公网 HTTPS、OpenAPI、管理 UI 和脱敏服务日志。

## 验收

```bash
curl --fail http://127.0.0.1:8091/api/v1/health
systemctl status weixin-bot-notification-platform.service
systemctl status weixin-bot-notification-platform-bot.service
journalctl -u weixin-bot-notification-platform.service --since today
```

真实投递的验收必须同时检查用户的 `delivery_ready`、worker 脱敏日志、投递状态和实际微信收件。`queued`、`dry-run` 或 `waiting_interaction` 不代表已经送达。
