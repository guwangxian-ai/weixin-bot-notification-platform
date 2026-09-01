# Weixin 投递

## 复用方式
`app/ilink_binding.py` 是已安装 Hermes `gateway.platforms.weixin` 二维码原语的薄适配层；`app/weixin_delivery.py` 调用其直接发送能力；`app/bot_worker.py` 为数据库中每个在职、已分配 Bot 启动独立 `WeixinAdapter` 长轮询。项目不 Fork、不修改 Hermes 核心。

## 专属凭据
每次成功扫码产生一组独立 Bot 凭据并加密存入 `weixin_bot_accounts`，不通过中央 Bot token 配置。`EMPLOYEE_BOT_HERMES_HOME` 仅用于适配器运行状态；context token 由 worker 转发给后端后使用 Fernet 加密存入 `employee_bot_bindings.context_token_encrypted`。worker 的适配器使用内存 token store，真实发送时只在权限为 `0700` 的临时目录短暂解密，完成后立即删除。不得复用任何其他项目的管理 Bot。

## 模式
- `mock`：确定性模拟发送，适合自动化测试。
- `dry-run`：记录计划但不触达微信。
- `weixin`：只有专属凭据齐全时配置校验才通过。

## 首条消息与 context token
扫码确认返回的 owner user ID 会作为加密的预备直达目标，但 iLink `bot_type=3` 在目标用户尚未给 Bot 发送首条消息时不允许 Bot 主动发出第一条消息。首次用户入站携带的 context token 和实际 chat ID 加密入库后，API 才返回 `delivery_ready=true`，并自动补发“绑定成功”和其他 `waiting_interaction` 任务。平台不会在 context 缺失时调用真实发送，避免将 iLink 的 `ret=-2 / prepare failed` 误报为普通限流。发送失败保留任务、失败码、人类提示与重试次数，`queued`、`dry-run` 和 `waiting_interaction` 都不得对外称为发送成功。

iLink 主动发送限流会安全映射为 `weixin_rate_limited`，响应提示 30 秒后重试并设置 `next_retry_at`；重试接口在该时间前返回 409。不得把限流伪装成已发送，也不得通过更换幂等键制造重复通知。

## 入站策略与可观测性
- 不使用 Hermes 的 `dm_policy=open`：该策略除非额外开启 `WEIXIN_ALLOW_ALL_USERS`，否则会在 callback 前拒绝私聊；开启全量用户又不符合员工专属 Bot 的授权边界。
- worker 从扫码结果解密 owner ID，为每个独立 Bot 配置 `dm_policy=allowlist` 和唯一 owner；API 仍二次校验 account fingerprint 与 owner ID。
- 每个 account 使用独立的 `<account>.sync.json` 游标，并通过 Hermes 机器级 token 锁保证本机只有一个消费者。systemd unit 必须允许写入专用状态目录和机器锁目录。
- 安全日志只记录员工 ID 的不可逆 HMAC 短引用、owner 是否匹配、是否携带 context、item 数量和 API 状态；Hermes adapter 自身日志在该 worker 中 fail-closed 屏蔽，不记录微信 ID、token、context、消息正文、URL、upstream errmsg 或原始异常内容。

## 媒体
视频仅作为一次性附件暂存，并通过官方 Weixin CDN 原生发送。上传和投递都强制执行 `APP_NATIVE_VIDEO_MAX_BYTES`，超限文件在发送前拒绝，不再降级为随后失效的下载链接。创建通知时用数据库原子条件更新将附件绑定到唯一 delivery，先提交 `PENDING` 和占用记录，再调用微信；并发请求不能重复使用同一附件。若进程在提交后、取得发送租约前中断，相同幂等请求会原子接管无租约的 `PENDING` 原记录，不新建通知。视频先于文字发送，`media_sent_at` 与 `text_sent_at` 分阶段提交，重试只补发未完成阶段，避免重复发送已成功的文字或视频。每次真实发送使用不可外泄的数据库租约令牌；阶段执行前续租并按令牌条件提交结果，活动租约期间禁止重试和取消，过期的 `SENDING` / `RETRYING` 可由管理员通过原记录重试恢复。真实媒体发送成功并提交阶段状态后，平台才删除暂存文件并写入审计；待互动、媒体发送失败和模拟发送均不删除文件。通知、附件元数据和审计历史继续保留。

## 运维
- 真实环境设置 `APP_DELIVERY_MODE=weixin`，并启用 `weixin-bot-notification-platform-bot.service`。
- 安装服务前先安装 `deploy/weixin-bot-notification-platform.conf` 到 `/etc/tmpfiles.d/`，执行 `systemd-tmpfiles --create /etc/tmpfiles.d/weixin-bot-notification-platform.conf`，再安装/启动 Bot unit。该规则会以服务账号创建权限为 `0700` 的 token 锁目录，避免干净主机因 `ReadWritePaths` 目标不存在而启动失败。
- 每个在职员工仅启动其独立 Bot 凭据的官方 `WeixinAdapter` 长轮询；正式 worker 必须是该 token 唯一的本机消费者。
- 扫码确认后，页面会保留二维码窗口并提示在新 Bot 会话发送任意消息。收到首条入站后，平台自动发送绑定成功通知并将 Bot 标记为健康可用。
- 扫码创建的是独立 `@im.bot` 身份，不是扫码人的普通微信账号。用户后续可在收到绑定成功通知的独立 Bot 会话中回复指令；发给扫码账号自身、文件传输助手、普通群聊或在群里 @ 扫码账号都不会进入该 Bot 的 `getUpdates`。
- worker 每五分钟记录一次脱敏 `getUpdates` 汇总；有消息时立即记录消息数、owner/target 匹配数、context 数和游标是否变化，不记录响应内容或任何外部标识。
- 验收时同时检查 API 的 `delivery_ready`、数据库密文存在、worker 入站日志、投递状态及 iLink 返回；只接受官方成功返回与数据库 `sent`，不接受队列或模拟结果。
- iLink sync cursor 只保证向前消费，不保证历史消息重放。若错误策略已推进游标，修复后清空游标只能重新建立当前位置，不能伪造或恢复已丢失的 context token。
