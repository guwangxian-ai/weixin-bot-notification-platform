# 贡献指南

感谢你对项目的关注。开发者与维护者：**猫王AI**。

## 开发流程

1. Fork 仓库并从 `main` 创建功能分支。
2. 使用 `uv sync --frozen --dev` 和 `npm --prefix web ci` 安装锁定依赖。
3. 保持修改聚焦，涉及数据模型时增加 Alembic 迁移。
4. 对行为变更增加回归测试。
5. 提交 Pull Request 前运行：

```bash
.venv/bin/ruff check app tests alembic scripts
.venv/bin/mypy app
.venv/bin/pytest -q
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build
```

## 安全要求

- 不得在代码、测试、Issue 或 PR 中包含真实密钥、Bot Token、手机号、微信标识和业务数据。
- 所有管理写操作必须经过后端 RBAC、租户校验和 CSRF 校验。
- 通知对象必须通过稳定 ID 解析，不得依赖名称猜测。
- 请使用 `SECURITY.md` 中的私密渠道报告漏洞。

## 提交风格

推荐使用 Conventional Commits，例如 `feat: add tenant export`、`fix: protect revoked bot delivery`。
