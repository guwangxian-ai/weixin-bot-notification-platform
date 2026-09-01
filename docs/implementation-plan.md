# 实施计划

## 已确认现状
- Hermes Agent v0.20.0（2026.8.3），源码位于 `/home/ubuntu/.hermes/hermes-agent`。
- 官方 Weixin 适配器支持长轮询、上下文 token 持久化、原生视频/文件上传、直接投递与会话失效处理。
- iLink 一个 token 只能由一个轮询器占用；现有管理 Bot 属于其他 Profile，禁止复用。
- Nginx 已占用公网 80/443，现有业务监听 `127.0.0.1:8080`；`127.0.0.1:8091` 检查为空闲。
- 目标项目目录在实施前不存在；`douyin-ai-leads` 工作区未被修改。

## 技术方案
- Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + SQLite WAL（单机首发，可迁移 PostgreSQL）。
- React + TypeScript + Vite 管理端，构建后由 FastAPI 同源托管。
- Session Cookie 登录、Argon2 密码、CSRF、防暴力登录；RBAC 角色：super_admin/company_admin/viewer。
- Hermes 官方 `gateway.platforms.weixin.WeixinAdapter` 作为可选运行时依赖，通过独立适配进程和专属 Hermes home 使用独立员工 Bot 凭据；mock 为默认模式。
- 业务 API 与 Bot 入站使用服务内确定性命令路由；仅 AI 改写类命令进入明确的 AI 任务接口。
- 内部监听 `127.0.0.1:8091`，Nginx 仅新增精确前缀 location。

## 阶段
1. 基线与备份：记录边界、备份 Nginx/服务参考配置、初始化 Git。
2. 数据与认证：迁移、模型、登录/RBAC、审计、租户隔离。
3. 业务闭环：员工、绑定码、绑定/解绑、视频资产、安全下载、投递状态机与幂等。
4. Bot：mock/dry-run、确定性指令、Hermes Weixin 适配接口、待领取补发。
5. 管理端：概览、公司、员工、绑定、资产、投递、Bot、日志、设置。
6. Skill 与文档：稳定 API 客户端，不暴露微信秘密。
7. 质量门：单元/集成/安全测试、Ruff、MyPy、前端 lint/build、OpenAPI。
8. 部署：systemd、Nginx、健康检查、浏览器验证、部署前标签。

## 数据与安全关键决策
- 所有租户业务表包含 `company_id`；查询仓储要求显式租户上下文。
- 微信标识加密存储，另存 HMAC 指纹用于唯一约束；API 仅返回掩码。
- 绑定码只存哈希，短时、单次、事务内消费；解绑同时撤销数据库授权。
- `idempotency_key` 在公司范围唯一；发送成功仅为 `sent`，员工回复“已收到”才为 `confirmed`。
- context token 缺失/过期进入 `waiting_interaction`，后续允许消息刷新上下文并补发。
- 下载使用随机短期签名票据，只解析数据库登记的资产路径，禁止任意路径访问。

## 暂不阻塞开发的外部项
- 专属员工微信 iLink Bot 尚无扫码凭据：实现并验证 mock 全闭环，最后只保留扫码配置步骤。
- AI 改写任务先提供受控接口与审计边界；无新增模型凭据时不自动启用。
