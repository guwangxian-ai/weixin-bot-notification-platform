# 变更记录

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的组织方式。

## [Unreleased]

### 新增

- README 中的自愿开源赞助说明和微信收款码。
- 用户对象创建时可选的语义化 `routing_key` 和可编辑用途说明；路由标识内部复用稳定 `target_code`。
- 面向业务接入的对象预览、显式分类映射与未知分类零发送指南。

### 变更

- 用户对象列表与接入信息使用权威 `user_object_code`；已有 `uo_<random>` 对象保持原编码和路由语义。

## [0.2.0] - 2026-09-01

### 新增

- 多公司租户、RBAC 与 CSRF 防护。
- 用户对象与多联系人 Bot 管理。
- 腾讯 iLink 二维码绑定、独立加密 Bot 凭据与 Worker。
- 按用户对象展开、Bot 去重、幂等批次和逐 Bot 投递。
- 文本、图片、文件、视频通知与定时状态查询。
- 公司级 API Client、一次性 Token 和最小权限对象范围。
- React 管理台、Alembic 迁移、发布校验和公开项目文档。

### 开发者

- 猫王AI
