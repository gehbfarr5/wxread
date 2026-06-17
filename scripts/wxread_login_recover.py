#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import requests

from telegram_notify import LOGIN_EXPIRED_MESSAGE, send_message, send_photo


READ_URL = "https://weread.qq.com/web/book/read"
HOME_URL = "https://weread.qq.com/"
COOKIE_ALLOWLIST = {
    "wr_vid",
    "wr_skey",
    "wr_rt",
    "wr_localvid",
    "wr_fp",
    "wr_gid",
    "wr_gender",
    "wr_avatar",
    "wr_name",
    "wr_ql",
}


def import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print(
            "Missing dependency: playwright\n"
            "Install with:\n"
            "  python3 -m pip install -r requirements-capture.txt\n"
            "  python3 -m playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return sync_playwright


def shell_quote(value):
    return shlex.quote(value or "")


def build_cookie_string(cookies):
    selected = []
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if name in COOKIE_ALLOWLIST and value:
            selected.append((name, value))
    selected.sort()
    return "; ".join(f"{name}={value}" for name, value in selected)


def validate_cookie_string(cookie_string):
    keys = set()
    for part in cookie_string.split(";"):
        part = part.strip()
        if "=" in part:
            keys.add(part.split("=", 1)[0])
    missing = {"wr_vid", "wr_skey", "wr_rt"} - keys
    return keys, missing


def build_curl(cookie_string, user_agent):
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://weread.qq.com",
        "referer": "https://weread.qq.com/",
        "user-agent": user_agent,
    }
    parts = ["curl", shell_quote(READ_URL)]
    for key, value in headers.items():
        parts.extend(["-H", shell_quote(f"{key}: {value}")])
    parts.extend(["-b", shell_quote(cookie_string)])
    return " ".join(parts)


def control_request(method, payload=None):
    base_url = os.getenv("WXREAD_RECOVERY_CONTROL_URL", "").rstrip("/")
    token = os.getenv("WXREAD_RECOVERY_CONTROL_TOKEN", "")
    if not base_url or not token:
        return None

    headers = {"x-wxread-token": token}
    url = f"{base_url}/api/state"
    if method == "GET":
        response = requests.get(url, headers=headers, timeout=20)
    else:
        response = requests.post(url, headers=headers, json=payload or {}, timeout=20)
    response.raise_for_status()
    return response.json().get("state")


def update_state(**patch):
    try:
        return control_request("POST", patch)
    except Exception as exc:
        print(f"Warning: failed to update recovery state: {exc}", file=sys.stderr)
        return None


def get_state():
    try:
        return control_request("GET")
    except Exception as exc:
        print(f"Warning: failed to read recovery state: {exc}", file=sys.stderr)
        return None


def write_secret_with_gh(output, environment):
    gh_token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not gh_token:
        raise RuntimeError("GH_TOKEN or GITHUB_TOKEN is required to update GitHub secrets")

    commands = []
    if environment:
        commands.append(["gh", "secret", "set", "WXREAD_CURL_BASH", "--env", environment])
    else:
        commands.append(["gh", "secret", "set", "WXREAD_CURL_BASH"])

    for command in commands:
        with output.open("rb") as handle:
            subprocess.run(command, stdin=handle, check=True)


def run_local_verify(output, read_num):
    env = os.environ.copy()
    env["WXREAD_CURL_BASH"] = output.read_text(encoding="utf-8")
    env["READ_NUM"] = str(read_num)
    env["PUSH_METHOD"] = ""
    subprocess.run([sys.executable, "main.py"], env=env, check=True)


def trigger_read_workflow(workflow):
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required to trigger the read workflow")

    env = os.environ.copy()
    env["GH_TOKEN"] = token
    subprocess.run(["gh", "workflow", "run", workflow], env=env, check=True)


def open_login_qr(page, start_url):
    page.goto(start_url, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    login = page.get_by_text("登录", exact=True)
    if login.count() > 0 and login.first.is_visible():
        login.first.click()
        page.wait_for_timeout(5000)


def get_qr_element(page):
    page.wait_for_function(
        """() => {
            const candidates = Array.from(document.querySelectorAll('img,canvas'))
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    const src = el.getAttribute('src') || '';
                    const squareEnough = Math.abs(rect.width - rect.height) <= 20;
                    const usefulSize = rect.width >= 120 && rect.height >= 120;
                    const visible = rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0;
                    const likelyQr = src.startsWith('data:image') || el.tagName === 'CANVAS';
                    return { el, rect, visible, usefulSize, squareEnough, likelyQr };
                })
                .filter((item) => item.visible && item.usefulSize && item.squareEnough && item.likelyQr);
            return candidates.length > 0;
        }""",
        timeout=20000,
    )
    handle = page.evaluate_handle(
        """() => {
            const candidates = Array.from(document.querySelectorAll('img,canvas'))
                .map((el) => {
                    const rect = el.getBoundingClientRect();
                    const src = el.getAttribute('src') || '';
                    const squareEnough = Math.abs(rect.width - rect.height) <= 20;
                    const usefulSize = rect.width >= 120 && rect.height >= 120;
                    const visible = rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0;
                    const likelyQr = src.startsWith('data:image') || el.tagName === 'CANVAS';
                    const score = (src.startsWith('data:image') ? 1000 : 0) + rect.width * rect.height;
                    return { el, visible, usefulSize, squareEnough, likelyQr, score };
                })
                .filter((item) => item.visible && item.usefulSize && item.squareEnough && item.likelyQr)
                .sort((a, b) => b.score - a.score);
            return candidates[0].el;
        }"""
    )
    element = handle.as_element()
    if element is None:
        raise RuntimeError("Could not locate WeRead login QR element")
    return element


def send_qr_snapshot(page, output_dir, sequence, caption):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"wxread-login-{sequence}.png"
    qr = get_qr_element(page)
    qr.screenshot(path=str(path))
    send_photo(path, caption=caption)
    return path


def main():
    parser = argparse.ArgumentParser(description="Recover WeRead web login by sending QR code to Telegram.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("/tmp/WXREAD_CURL_BASH.web"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("/tmp/wxread-login"))
    parser.add_argument("--verify-read-num", type=int, default=1)
    parser.add_argument("--environment", default=os.getenv("WXREAD_SECRET_ENVIRONMENT", "AutoRead"))
    parser.add_argument("--read-workflow", default=os.getenv("WXREAD_READ_WORKFLOW", "deploy.yml"))
    parser.add_argument("--start-url", default=HOME_URL)
    args = parser.parse_args()

    sync_playwright = import_playwright()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    update_state(status="starting", lastMessage="登录恢复 workflow 已启动，正在生成二维码。")

    sequence = 1
    last_refresh_seen = None
    deadline = time.time() + args.timeout

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="zh-CN")
            page = context.new_page()
            open_login_qr(page, args.start_url)

            update_state(status="waiting_for_scan", lastMessage="二维码已生成，等待微信扫码。")
            send_qr_snapshot(page, args.artifact_dir, sequence, LOGIN_EXPIRED_MESSAGE)

            while time.time() < deadline:
                state = get_state()
                if state and state.get("cancelRequestedAt"):
                    update_state(status="cancelled", lastMessage="已按 Telegram 命令取消。")
                    send_message("❌ 微信读书登录恢复已取消。")
                    return 1

                refresh_requested_at = state.get("refreshRequestedAt") if state else None
                if refresh_requested_at and refresh_requested_at != last_refresh_seen:
                    last_refresh_seen = refresh_requested_at
                    sequence += 1
                    open_login_qr(page, args.start_url)
                    update_state(status="waiting_for_scan", lastMessage="二维码已刷新，等待微信扫码。")
                    send_qr_snapshot(
                        page,
                        args.artifact_dir,
                        sequence,
                        "🔄 已刷新微信读书登录二维码。\n\n📱 请使用微信扫描下方二维码。",
                    )

                cookies = context.cookies("https://weread.qq.com")
                cookie_string = build_cookie_string(cookies)
                keys, missing = validate_cookie_string(cookie_string)
                if not missing:
                    user_agent = page.evaluate("() => navigator.userAgent")
                    args.output.write_text(build_curl(cookie_string, user_agent), encoding="utf-8")
                    update_state(status="verifying", lastMessage="扫码登录成功，正在验证新 cURL。")
                    send_message("✅ 微信读书扫码登录成功，正在验证并写回 GitHub Secret。")
                    context.close()
                    browser.close()
                    break

                page.wait_for_timeout(args.poll_interval * 1000)
            else:
                update_state(status="timeout", lastMessage="15 分钟内未完成扫码登录。")
                send_message("⏰ 微信读书登录恢复已超时。\n\n请发送 /wxread_login 重新开始。")
                context.close()
                browser.close()
                return 1

        run_local_verify(args.output, args.verify_read_num)
        update_state(status="persisting", lastMessage="新 cURL 验证通过，正在写回 GitHub Secret。")
        write_secret_with_gh(args.output, args.environment)
        update_state(status="triggering_read", lastMessage="Secret 已写回，正在触发正常阅读任务。")
        send_message("✅ 微信读书登录恢复成功。\n\n🔐 WXREAD_CURL_BASH 已写回 GitHub Secret。\n🚀 正在触发一次正常阅读任务。")
        trigger_read_workflow(args.read_workflow)
        update_state(status="complete", lastMessage="登录恢复完成，正常阅读任务已触发。")
        return 0
    except Exception as exc:
        update_state(status="failed", lastMessage=f"登录恢复失败：{exc}")
        try:
            send_message(f"❌ 微信读书登录恢复失败。\n\n原因：{exc}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
