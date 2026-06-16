#!/usr/bin/env python3
import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


READ_URL = "https://weread.qq.com/web/book/read"
DEFAULT_START_URL = "https://weread.qq.com/"
DEFAULT_PROFILE = Path.home() / ".wxread-capture-chrome"
DEFAULT_OUTPUT = Path("/tmp/WXREAD_CURL_BASH.web")
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
HEADER_BLOCKLIST = {
    "cookie",
    "content-length",
    "host",
    "origin-policy",
}


def import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print(
            "Missing dependency: playwright\n"
            "Install once with:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return sync_playwright


def shell_quote(value):
    return shlex.quote(value or "")


def normalize_headers(headers):
    result = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key in HEADER_BLOCKLIST or lower_key.startswith(":"):
            continue
        if lower_key.startswith("sec-fetch") or lower_key.startswith("sec-ch-"):
            continue
        result[key] = value
    return result


def build_cookie_string(cookies):
    selected = []
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if name in COOKIE_ALLOWLIST and value:
            selected.append((name, value))
    selected.sort()
    return "; ".join(f"{name}={value}" for name, value in selected)


def build_curl(url, headers, cookie_string):
    parts = ["curl", shell_quote(url)]
    for key, value in headers.items():
        parts.extend(["-H", shell_quote(f"{key}: {value}")])
    parts.extend(["-b", shell_quote(cookie_string)])
    return " ".join(parts)


def validate_cookie_string(cookie_string):
    keys = set()
    for part in cookie_string.split(";"):
        part = part.strip()
        if "=" in part:
            keys.add(part.split("=", 1)[0])
    missing = {"wr_vid", "wr_skey", "wr_rt"} - keys
    return keys, missing


def write_secret_with_gh(output, environment):
    commands = []
    if environment:
        commands.append(["gh", "secret", "set", "WXREAD_CURL_BASH", "--env", environment])
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


def main():
    parser = argparse.ArgumentParser(
        description="Capture a durable WeRead /web/book/read cURL from a dedicated Chrome profile."
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--start-url", default=DEFAULT_START_URL)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--debug-requests", action="store_true")
    parser.add_argument("--verify-local", action="store_true")
    parser.add_argument("--verify-read-num", type=int, default=1)
    parser.add_argument("--update-github-secret", action="store_true")
    parser.add_argument("--environment", default=os.getenv("WXREAD_SECRET_ENVIRONMENT", "AutoRead"))
    args = parser.parse_args()

    sync_playwright = import_playwright()
    args.profile.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    captured = {}
    diagnostics = {
        "read_requests": 0,
        "saw_guest": False,
        "last_missing": [],
    }

    with sync_playwright() as playwright:
        browser_kwargs = {
            "user_data_dir": str(args.profile),
            "headless": args.headless,
        }
        try:
            context = playwright.chromium.launch_persistent_context(channel="chrome", **browser_kwargs)
        except Exception:
            context = playwright.chromium.launch_persistent_context(**browser_kwargs)

        page = context.pages[0] if context.pages else context.new_page()

        seen_urls = set()

        def on_request(request):
            if "weread.qq.com" not in request.url:
                return
            if "Web_EnterGuest" in request.url or "promoGuestId" in request.url:
                diagnostics["saw_guest"] = True
            if args.debug_requests and request.url not in seen_urls:
                seen_urls.add(request.url)
                print(f"{request.method} {request.url}")
            if request.method != "POST" or not request.url.startswith(READ_URL):
                return

            diagnostics["read_requests"] += 1
            headers = normalize_headers(request.all_headers())
            cookies = context.cookies("https://weread.qq.com")
            cookie_string = build_cookie_string(cookies)
            keys, missing = validate_cookie_string(cookie_string)
            if missing:
                diagnostics["last_missing"] = sorted(missing)
                print(
                    "Captured /web/book/read, but cookie is not durable. "
                    f"Missing: {', '.join(sorted(missing))}. "
                    "Keep the page open and trigger another read request after the web login is fully loaded."
                )
                return
            captured["curl"] = build_curl(request.url, headers, cookie_string)
            captured["keys"] = keys

        context.on("request", on_request)
        print("A dedicated Chrome window is open.")
        print("1. Log in at https://weread.qq.com if needed.")
        print("2. Open a book in the web reader.")
        print("3. Turn one page to trigger /web/book/read.")
        print(f"Waiting up to {args.timeout} seconds for a durable cURL with wr_rt...")
        page.goto(args.start_url, wait_until="domcontentloaded")

        deadline_ms = args.timeout * 1000
        step_ms = 500
        elapsed = 0
        while elapsed < deadline_ms and "curl" not in captured:
            page.wait_for_timeout(step_ms)
            elapsed += step_ms

        context.close()

    if "curl" not in captured:
        if diagnostics["read_requests"] == 0:
            if diagnostics["saw_guest"]:
                print(
                    "Diagnostics: only guest/home requests were observed. "
                    "Log in inside the dedicated Chrome window, open a book reader, and turn one page.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Diagnostics: no /web/book/read request was observed. "
                    "Open a book reader and turn one page in the dedicated Chrome window.",
                    file=sys.stderr,
                )
        elif diagnostics["last_missing"]:
            print(
                "Diagnostics: /web/book/read was observed, but cookie validation failed. "
                f"Missing: {', '.join(diagnostics['last_missing'])}.",
                file=sys.stderr,
            )
        print("No durable /web/book/read cURL captured.", file=sys.stderr)
        raise SystemExit(1)

    args.output.write_text(captured["curl"], encoding="utf-8")
    print(f"Wrote cURL to {args.output}")
    print("Cookie validation: wr_vid, wr_skey, and wr_rt are present.")

    if args.verify_local:
        print(f"Running local verification with READ_NUM={args.verify_read_num}...")
        run_local_verify(args.output, args.verify_read_num)
        print("Local verification passed.")

    if args.update_github_secret:
        print("Updating GitHub WXREAD_CURL_BASH secret...")
        write_secret_with_gh(args.output, args.environment)
        print("GitHub secret updated.")


if __name__ == "__main__":
    main()
