# 微信读书登录恢复闭环

## 目标

当 `WXREAD_CURL_BASH` 失效时，通过 Telegram 触发登录恢复：

1. 正常阅读 workflow 发送失效通知。
2. 在 Telegram 发送 `/wxread_login`。
3. Cloudflare Worker 触发 `wxread-login` GitHub workflow。
4. workflow 生成微信读书二维码并发到 Telegram。
5. 使用微信扫码。
6. workflow 自动生成新的 `WXREAD_CURL_BASH`，验证后写回 GitHub Secret。
7. workflow 自动触发一次正常阅读任务。

## Telegram 命令

```text
/wxread_login    启动微信读书登录恢复
/wxread_refresh  刷新微信读书登录二维码
/wxread_status   查看微信读书恢复状态
/wxread_cancel   取消微信读书登录恢复
```

## GitHub 配置

已有配置：

- Repository variable: `READ_NUM=130`
- Repository variable: `WXREAD_SECRET_ENVIRONMENT=AutoRead`
- Secret: `TELEGRAM_BOT_TOKEN`
- Secret: `TELEGRAM_CHAT_ID`
- Secret: `GH_PAT_FOR_SECRET_UPDATE`
- Secret: `WXREAD_CURL_BASH`

新增配置：

- Repository variable: `WXREAD_RECOVERY_CONTROL_URL`
  - Cloudflare Worker URL，例如 `https://wxread-telegram-worker.example.workers.dev`
- Secret: `WXREAD_RECOVERY_CONTROL_TOKEN`
  - GitHub workflow 和 Worker 之间的共享控制 token。

## Cloudflare Worker 配置

Worker 目录在 `worker/`。

需要创建 KV namespace，并把 namespace id 填入 `worker/wrangler.toml`：

```toml
[[kv_namespaces]]
binding = "WXREAD_STATE"
id = "replace-with-cloudflare-kv-namespace-id"
```

Worker secrets:

```bash
cd worker
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHAT_ID
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put GITHUB_REPOSITORY
npx wrangler secret put WXREAD_RECOVERY_CONTROL_TOKEN
npx wrangler secret put WEBHOOK_SECRET
```

建议值：

- `GITHUB_REPOSITORY`: `gehbfarr5/wxread`
- `GITHUB_TOKEN`: 有 `workflow` 权限的 GitHub token，用于触发 `wxread-login.yml`
- `WEBHOOK_SECRET`: 随机字符串，用于保护 Telegram webhook 路径

部署：

```bash
cd worker
npm install
npx wrangler deploy
```

部署后设置 Telegram webhook 和命令：

```bash
curl -X POST "$WXREAD_RECOVERY_CONTROL_URL/admin/set-webhook" \
  -H "x-wxread-token: $WXREAD_RECOVERY_CONTROL_TOKEN"

curl -X POST "$WXREAD_RECOVERY_CONTROL_URL/admin/set-commands" \
  -H "x-wxread-token: $WXREAD_RECOVERY_CONTROL_TOKEN"
```

也可以在 GitHub Actions 手动运行 `telegram-bot-commands` workflow 来替换 Telegram bot 命令。

## 恢复消息

失效通知：

```text
⚠️ 微信读书登录态已失效。

📱 请使用微信扫描下方二维码。
⏳ 二维码有效期较短。

🧭 命令：
/wxread_refresh  🔄 刷新二维码
/wxread_status   📊 查看状态
/wxread_cancel   ❌ 取消
```

成功通知：

```text
✅ 微信读书登录恢复成功。

🔐 WXREAD_CURL_BASH 已写回 GitHub Secret。
🚀 正在触发一次正常阅读任务。
```
