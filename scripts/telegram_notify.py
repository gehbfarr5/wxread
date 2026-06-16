import os
import time
from pathlib import Path

import requests


LOGIN_EXPIRED_MESSAGE = """⚠️ 微信读书登录态已失效。

📱 请使用微信扫描下方二维码。
⏳ 二维码有效期较短。

🧭 命令：
/wxread_refresh  🔄 刷新二维码
/wxread_status   📊 查看状态
/wxread_cancel   ❌ 取消"""


def _telegram_request(method, payload=None, files=None, attempts=4):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{token}/{method}"
    proxies = {
        "http": os.getenv("http_proxy"),
        "https": os.getenv("https_proxy"),
    }
    last_error = None

    for attempt in range(attempts):
        try:
            response = requests.post(
                url,
                data=payload if files else None,
                json=payload if not files else None,
                files=files,
                proxies=proxies,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(2 + attempt * 3)

    raise RuntimeError(f"Telegram {method} failed: {last_error}") from last_error


def send_message(text):
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")
    return _telegram_request("sendMessage", {"chat_id": chat_id, "text": text})


def send_photo(photo_path, caption=None):
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not configured")
    path = Path(photo_path)
    with path.open("rb") as handle:
        return _telegram_request(
            "sendPhoto",
            payload={"chat_id": chat_id, "caption": caption or ""},
            files={"photo": (path.name, handle, "image/png")},
        )
