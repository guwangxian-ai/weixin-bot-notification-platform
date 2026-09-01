# 架构

## 组件
- FastAPI：REST/OpenAPI、认证、RBAC、租户隔离、静态 Web 托管。
- React/Vite：管理员工作台，所有权限仍由后端强制。
- SQLAlchemy/Alembic/SQLite WAL：正式模型、迁移和审计；可迁移 PostgreSQL。
- Hermes Weixin 薄适配层：二维码创建/轮询复用官方 `_api_get` 与常量，投递复用 `send_weixin_direct`，入站复用 `WeixinAdapter`；不复制协议、不修改核心。
- Nginx：TLS 入口和固定子路径代理；Uvicorn 只监听 `127.0.0.1:8091`。

## 信任边界
浏览器只持有 HttpOnly 签名 Session Cookie；修改请求需 CSRF。Hermes Skill 使用独立服务令牌。Bot 入站使用独立共享密钥。微信 token、context token 和完整用户/会话标识永不进入前端或 Skill。

## 多租户
所有业务实体带 `company_id`。`super_admin` 可跨公司；`company_admin` 与 `viewer` 的公司范围由后端查询与对象级检查共同执行。幂等键在公司范围唯一。

## 通知投递状态机
通知由独立标题、正文和可选视频附件组成。真实通道为 `pending → sending → sent → confirmed`；失败进入 `failed`，重试时进入 `retrying`；缺少可用上下文进入 `waiting_interaction`；管理员可对未确认任务设为 `cancelled`。隔离 mock/dry-run 使用独立的 `simulated` 终态，不计作 `sent`，也不能升级为 `confirmed`。API 接受或模拟成功均不等于员工确认。

## AI 边界
绑定状态机为 `pending → scanned → confirming → bound`，旁路终态为 `expired / cancelled / failed / revoked`。独立 Bot 与员工通过分配表关联，解除后账号可用同公司事务转交。绑定、通知、领取、确认、退订和帮助由确定性代码处理；普通 Bot 输入不会进入模型。
