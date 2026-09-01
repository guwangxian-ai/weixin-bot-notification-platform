# 用户对象信息架构与兼容决策

## 术语与边界

“用户对象”是公司下的业务/内容账号，不是 `users` 表中的管理员登录账号。数据库中的 `NotificationTarget`、稳定 `target_code`、旧 API 路径和历史通知记录继续保留；新界面隐藏底层模式与编码。

页面层级为：公司 → 用户对象（账号）→ 联系人及其个人微信 Bot。独立“微信 Bot”导航已移除，Bot 生命周期操作归入用户对象详情。

## 新对象

管理员通过 `POST /api/v1/companies/{company_id_or_slug}/user-objects` 仅提交 `account_name`。服务端生成不可猜测的 `user_object_code`，内部使用兼容的 `multi` target，并通过 `user_object_contacts` 保存稳定的对象—联系人关系。对象可有 0、1 或多个联系人；发送时解析每名 active 联系人当前 active Bot binding。

联系电话先规范化，再用平台既有 Fernet key 加密；检索指纹使用带用途域分离的 HMAC。数据库不保存明文。业务 Token 只得到脱敏电话；授权管理 Session 才能得到编辑所需的规范化电话。API、审计和错误均不得包含密文、指纹或微信凭据。

## 旧数据兼容

- 旧 `notification-targets` API、`target_code`、`single`、`multi`、`dynamic_all` 和 employee compatibility target 全部保留。
- 新 UI 不显示模式。
- 旧 single/multi 对象在别名 API 中从现有 `target_bot_members` 映射联系人，不改历史 binding/member。
- employee compatibility target 继续按稳定 `employee_id` 跟随当前 active binding。
- `dynamic_all` 仍在每次预览/发送时动态展开该公司当时全部 active 员工与 active Bot；别名返回 `all_available=true`，UI 不允许把它静默转换成固定成员。
- 新用户对象使用稳定联系人关系，不修改旧对象的解析策略。

## 操作语义

- 从当前对象移除：仅软移除 `user_object_contacts` 关系；联系人、Bot、其他对象关系和历史不变。`DELETE .../contacts/{employee_id}` 必须在请求体提交 `{ "confirm": true }`，服务端不信任只有前端弹窗的确认。
- 解绑微信：复用现有确认、凭据清除、会话撤销、审计和并发保护链路；`POST .../unbind` 必须在请求体提交 `{ "confirm": true }`。
- 停用联系人：需要显式确认，将联系人状态改为 disabled；关系和历史保留，发送解析排除该联系人。`POST .../deactivate` 必须在请求体提交 `{ "confirm": true }`。旧 `/employees/{employee_id}` PATCH/DELETE 在联系人属于新式用户对象时也必须提交服务端确认，不能绕过该资源不变量。
- 删除用户对象：只允许新式用户对象，采用停用和软删除；旧兼容对象继续由旧 API 管理。`DELETE .../user-objects/{user_object_code}` 必须在请求体提交 `{ "confirm": true }`。
- 绑定全部可用 Bot：给新式用户对象幂等关联当前公司全部 active 联系人；`dynamic_all` 不执行固定化转换。
- 逐 Bot 测试：复用现有固定内容、冷却、配额、原子占用、审计和错误处理接口；HTTP 接受、mock 或 dry-run 不等同于真实微信送达。隔离 `mock` 模式持久化并返回 `SIMULATED`/`simulated`，批次成功数保持为 0，界面明确显示“仅模拟，未发送”；只有官方发送成功才能进入 `SENT`/`sent`。

## Bot 归属与回执围栏

`weixin_bot_accounts.company_id` 是非空、不可隐式转移的 Bot 公司归属。扫码确认、绑定写入和通知解析必须同时核对 Bot、binding、联系人和对象的 `company_id`；解绑不会清除 Bot 的公司归属，另一个公司不能通过重新扫码认领该 Bot。迁移遇到同一历史 Bot 跨公司绑定或无法确定唯一公司时会 fail closed，而不是猜测归属。

投递创建时保存实际使用的 `binding_id`。入站“已收到”只能确认同公司、同联系人且 `delivery.binding_id` 等于当前入站 binding 的历史投递；解绑、重新绑定或转移后的新 binding 不能确认旧 binding 产生的投递。这是 binding-version confirmation fencing，不以可变的当前员工/Bot 关系替代历史投递身份。

## 租户与调用

别名 API 的公司路径参数同时接受稳定 `company_id` 或 `company_slug`，对象通过同公司下的 `user_object_code` 精确解析。所有详情、关联、二维码、解绑、停用和删除都在后端重复校验公司所有权。业务 Profile 仍只允许查询、预览、幂等发送和状态查询；联系人/Bot 管理由平台管理员执行。
