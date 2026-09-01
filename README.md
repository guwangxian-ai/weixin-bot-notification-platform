# 通用多公司个人微信 Bot 通知平台

> 由 **猫王AI** 开发与维护

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](pyproject.toml)
[![React](https://img.shields.io/badge/React-18-61dafb.svg)](web/package.json)

一个行业无关、支持多公司租户的通知基础设施。管理员可创建用户对象，为每个用户绑定多个独立微信 Bot，并通过管理界面或 API 向用户发送文字、图片、文件、视频、任务提醒和系统告警。一个用户绑定了几个 Bot，通知就会扇出到几个 Bot。

## 核心能力

- 多公司租户隔离，所有业务数据和权限路径均按 `company_id` 限定。
- 用户对象管理，兼容单人、多人和动态全体通知对象。
- 每个用户可绑定多个独立个人微信 Bot，新增时展示二维码供用户扫码。
- 按用户发送测试通知，后端按 Bot 身份展开、去重并记录每个投递结果。
- 支持数据库 API Client、最小权限授权、幂等通知批次和状态查询。
- 联系信息、Bot 凭据和 context token 加密存储，完整凭据不进入 API、HTML 或日志。
- 通用媒体暂存、一次性附件、分阶段投递、重试、审计与运维观测。

## 架构

```text
管理员 / 业务系统
        │ Web UI / REST API
        ▼
FastAPI + SQLAlchemy + SQLite
        │ 通知批次与逐 Bot Delivery
        ▼
Bot Worker ── Hermes Weixin/iLink 适配器 ──► 独立微信 Bot
```

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、SQLAlchemy 2、Alembic |
| 数据 | SQLite WAL，支持迁移和一致性备份 |
| 前端 | React 18、TypeScript、Vite |
| 微信通道 | Hermes Weixin/iLink 适配器（薄封装） |
| 部署 | Uvicorn、systemd、Nginx |

## 快速开始

环境需求：Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 20+。

```bash
git clone https://github.com/guwangxian-ai/weixin-bot-notification-platform.git
cd weixin-bot-notification-platform

uv sync --frozen --dev
npm --prefix web ci

.venv/bin/python scripts/bootstrap_env.py
mkdir -p data uploads logs backups
.venv/bin/dotenv -f .env run -- .venv/bin/alembic upgrade head
npm --prefix web run build

.venv/bin/uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8091
```

首次运行 `bootstrap_env.py` 会在终端显示一次性初始管理员密码；请立即保存并在登录后更换。`.env` 被 Git 忽略，不应提交。

打开：

- 管理界面：`http://127.0.0.1:8091/`
- OpenAPI：`http://127.0.0.1:8091/api/docs`
- 健康检查：`http://127.0.0.1:8091/api/v1/health`

## 启动 Bot Worker

真实微信投递需先安装并配置兼容的 Hermes Weixin/iLink 运行环境，再将 `.env` 中 `APP_DELIVERY_MODE` 设为 `weixin`。

```bash
.venv/bin/dotenv -f .env run -- .venv/bin/python -m app.bot_worker
```

本地功能开发可使用 `mock` 或 `dry-run` 模式，两者均不会触达真实微信用户。

## 使用流程

1. 创建公司，并在公司下创建用户对象。
2. 进入用户详情，选择“添加微信 Bot”。
3. 将页面生成的二维码交给相应用户扫码，等待绑定成功。
4. 用户向新绑定的独立 Bot 会话发送一次消息，激活主动通知所需的 context token。
5. 在用户页面发送测试通知；系统会向该用户当前所有有效 Bot 各投递一次。

## 开发与验证

```bash
.venv/bin/ruff check app tests alembic scripts skill/employee-video-notification/scripts/client.py
.venv/bin/mypy app
.venv/bin/pytest -q
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build
APP_DATABASE_URL=sqlite:////tmp/weixin-bot-platform.db .venv/bin/alembic upgrade head
```

也可以直接执行 `scripts/verify-release.sh`。

## 部署

`deploy/` 包含通用 systemd、tmpfiles 和 Nginx 示例。默认示例假定：

- 应用目录：`/opt/weixin-bot-notification-platform`
- 服务账号：`weixinbot`
- 环境文件：`/etc/weixin-bot-notification-platform.env`
- 内部端口：`127.0.0.1:8091`
- 公网子路径：`/weixin-bot-notification-platform/`

请按实际服务器调整用户、目录、域名、TLS 和 Hermes 运行时路径。完整流程见 [部署文档](docs/deployment.md)。

## 安全说明

- 生产环境必须替换 `.env.example` 中的所有占位值，并限制环境文件权限。
- 不要提交 `.env`、数据库、上传文件、日志、备份、Bot 凭据或真实微信标识。
- 对外部署应使用 HTTPS、严格反向代理边界、独立服务账号和最小权限 API Client。
- 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中粘贴凭据。

## 微信集成边界

本项目的扫码流程会创建或绑定独立 `@im.bot` 身份，不是登录、接管或反向控制扫码人的普通微信账号。本项目与腾讯、微信无隶属、赞助或背书关系；使用者需自行确保所在地区、账号及业务场景符合相关规则。

## 文档索引

- [系统架构](docs/architecture.md)
- [数据库设计](docs/database.md)
- [API 文档](docs/api.md)
- [通用平台 API](docs/general-platform-api.md)
- [业务 Profile API](docs/business-profile-api.md)
- [用户对象兼容性](docs/user-object-compatibility.md)
- [微信投递](docs/weixin-delivery.md)
- [部署](docs/deployment.md)
- [运维](docs/operations.md)
- [故障排查](docs/troubleshooting.md)
- [贡献指南](CONTRIBUTING.md)
- [安全政策](SECURITY.md)
- [第三方说明](THIRD_PARTY_NOTICES.md)

## License

本项目由猫王AI以 [MIT License](LICENSE) 开源。
