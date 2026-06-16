# WeRead 自动化配置指南

## 方式一：GitHub Action 自动化运行（推荐）

### 步骤 1：Fork 项目

1. 访问 https://github.com/findmover/wxread
2. 点击右上角 Fork 按钮
3. Fork 到你的账号

### 步骤 2：获取 cURL 命令

**重要**：这是必需步骤！

#### 推荐：半自动捕获器

这个方式会启动一个独立 Chrome profile，不读取你的日常 Chrome Cookie 数据库。第一次需要在弹出的浏览器里登录微信读书；登录后 profile 会保留状态，后续只需要打开书并翻页触发一次请求。

```bash
python3 -m pip install -r requirements-capture.txt
python3 -m playwright install chromium

python3 scripts/capture_wxread_curl.py \
  --verify-local \
  --update-github-secret \
  --environment AutoRead
```

脚本会等待你在浏览器中打开一本书并翻页，捕获 `https://weread.qq.com/web/book/read`，校验 Cookie 中包含 `wr_vid`、`wr_skey`、`wr_rt` 后写入 `/tmp/WXREAD_CURL_BASH.web`。只有包含 `wr_rt` 的 Web 登录态才能支撑 `READ_NUM=130` 的 65 分钟运行和后续自动续期。

如果脚本一直等待，使用 `--debug-requests` 重跑。看到 `Web_EnterGuest` 或 `promoGuestId` 表示当前仍是游客态，需要在弹出的专用 Chrome 窗口里完成登录；没有 `/web/book/read` 表示还没有进入阅读页并翻页。

#### 手动 Chrome DevTools

1. 打开微信读书网页版：https://weread.qq.com/
2. 登录你的账号
3. 按 F12 打开开发者工具
4. 切换到 Network 标签
5. 搜索《三体》并打开阅读
6. 点击下一页翻页
7. 在 Network 列表中找到 `read` 请求
   - URL: `https://weread.qq.com/web/book/read`
   - Method: POST
8. 右键点击该请求 → Copy → Copy as cURL (bash)
9. 保存这个命令

### 步骤 3：配置 GitHub Secrets

在你的 Fork 仓库中：

1. 进入 **Settings** → **Secrets and variables** → **Actions**
2. 点击 **New repository secret**
3. 添加以下 secrets：

| Name | Value | 说明 |
|------|-------|------|
| `WXREAD_CURL_BASH` | 第2步复制的完整 cURL 命令 | **必需** |
| `GH_PAT_FOR_SECRET_UPDATE` | GitHub fine-grained personal access token | 推荐，用于自动写回更新后的 `WXREAD_CURL_BASH`。写 Repository secret 需要 `Secrets: Read and write`；写 Environment secret 需要 `Environments: Read and write` |
| `PUSH_METHOD` | `pushplus` 或 `wxpusher` 或 `telegram` 或 `serverchan` | 可选，推荐 pushplus |
| `PUSHPLUS_TOKEN` | 你的 PushPlus token | 如果选择 pushplus |
| `WXPUSHER_SPT` | 你的 WxPusher token | 如果选择 wxpusher |

### 步骤 4：配置 Variables

在 **Variables** 部分：

| Name | Value | 说明 |
|------|-------|------|
| `READ_NUM` | `130` | 阅读次数，130次 = 65分钟 |
| `WXREAD_SECRET_ENVIRONMENT` | `AutoRead` | 可选。仅当 `WXREAD_CURL_BASH` 配在 Environment secret 时填写；不填则写 Repository secret |

### 步骤 5：启用 GitHub Action

1. 进入 **Actions** 标签
2. 如果看到提示，点击 **I understand my workflows, go ahead and enable them**
3. 选择 **wxread** workflow
4. 点击 **Enable workflow**

### 步骤 6：测试运行

1. 在 **Actions** 页面
2. 选择 **wxread** workflow
3. 点击 **Run workflow** → **Run workflow**
4. 等待运行完成
5. 查看运行日志

---

## 定时任务

默认配置：
- 每天北京时间 01:00 运行

修改定时：
编辑 `.github/workflows/deploy.yml` 中的 cron 表达式：

```yaml
on:
  schedule:
    - cron: '0 17 * * *'  # UTC 17:00 = 北京时间 01:00
```

---

## 推送通知配置

### PushPlus（推荐）

1. 访问 https://www.pushplus.plus/uc.html
2. 微信扫码登录
3. 复制 token
4. 配置：
   - `PUSH_METHOD`: `pushplus`
   - `PUSHPLUS_TOKEN`: 你的 token

### WxPusher

1. 访问 https://wxpusher.zjiecode.com/docs/#/?id=获取spt
2. 关注公众号获取 spt
3. 配置：
   - `PUSH_METHOD`: `wxpusher`
   - `WXPUSHER_SPT`: 你的 spt

---

## 方式二：本地 Docker 运行

如果不想用 GitHub Action，可以本地运行：

```bash
cd ~/wxread

# 构建镜像
docker build -t wxread .

# 运行容器
docker run -d --name wxread \
  -v $(pwd)/logs:/app/logs \
  --restart always \
  -e WXREAD_CURL_BASH="你的curl命令" \
  -e READ_NUM=130 \
  wxread

# 测试运行
docker exec -it wxread python /app/main.py
```

---

## 备份的 Cookies 使用

备份的 cookies 在：`~/weread_backup/cookies.json`

但新项目需要完整的 cURL 命令，包括：
- headers
- cookies
- data 参数

**建议**：重新抓包获取完整数据

---

## 常见问题

### Q: Cookie 会过期吗？
A: 会的。脚本会尝试刷新 `wr_skey`，并在配置了 `GH_PAT_FOR_SECRET_UPDATE` 时自动写回 `WXREAD_CURL_BASH`。如果没有配置这个 GitHub token，本次运行内可以使用新密钥，但下一次 Action 仍会读取旧 secret。

### Q: 阅读时间不准确？
A: 确保 config.py 中保留了 data 字段，默认读三体。

### Q: GitHub Action 运行失败？
A: 检查 WXREAD_CURL_BASH 是否配置正确，确保是完整的 cURL 命令。

---

## 文件位置

- 新项目：`~/wxread/`
- 备份：`~/weread_backup/`
- 旧项目：`~/weread_old_20260425_120800/`
