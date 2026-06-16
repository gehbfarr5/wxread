#!/usr/bin/env python3
import os
import sys

import requests


COMMANDS = [
    {"command": "wxread_login", "description": "启动微信读书登录恢复"},
    {"command": "wxread_refresh", "description": "刷新微信读书登录二维码"},
    {"command": "wxread_status", "description": "查看微信读书恢复状态"},
    {"command": "wxread_cancel", "description": "取消微信读书登录恢复"},
]


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is required", file=sys.stderr)
        return 2

    response = requests.post(
        f"https://api.telegram.org/bot{token}/setMyCommands",
        json={"commands": COMMANDS},
        timeout=30,
    )
    print(response.text)
    response.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
