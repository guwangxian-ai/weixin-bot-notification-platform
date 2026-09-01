# 第三方软件声明

本项目自身使用 MIT License。安装与运行时会使用多个独立开源组件，包括但不限于：

- FastAPI、Starlette、Uvicorn；
- SQLAlchemy、Alembic、SQLite；
- React、Vite、TypeScript、Lucide React；
- APScheduler 相关运行环境（如外部集成使用）；
- Cryptography、HTTPX、aiohttp、qrcode。

各组件的许可条款以其上游发布包中的 License 为准。

## 微信 / iLink 集成

真实微信投递通过外部 Hermes Weixin/iLink 适配器提供。该适配器不包含在本仓库中，使用者必须自行确认其来源、版本、许可条款和微信平台要求。

本项目与腾讯、微信之间不存在官方背书或隶属关系。“微信”及其相关商标归其权利人所有。
