const STATE_KEY = "wxread:recovery";
const COMMANDS = [
  {
    command: "wxread_login",
    description: "启动微信读书登录恢复",
  },
  {
    command: "wxread_refresh",
    description: "刷新微信读书登录二维码",
  },
  {
    command: "wxread_status",
    description: "查看微信读书恢复状态",
  },
  {
    command: "wxread_cancel",
    description: "取消微信读书登录恢复",
  },
];

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
    },
  });
}

function getRequiredEnv(env, key) {
  const value = env[key];
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

async function getState(env) {
  const raw = await env.WXREAD_STATE.get(STATE_KEY);
  if (!raw) {
    return {
      status: "idle",
      updatedAt: new Date().toISOString(),
      refreshRequestedAt: null,
      cancelRequestedAt: null,
      runId: null,
      lastMessage: "尚未启动微信读书登录恢复。",
    };
  }
  return JSON.parse(raw);
}

async function putState(env, patch) {
  const state = {
    ...(await getState(env)),
    ...patch,
    updatedAt: new Date().toISOString(),
  };
  await env.WXREAD_STATE.put(STATE_KEY, JSON.stringify(state));
  return state;
}

async function callTelegram(env, method, payload) {
  const token = getRequiredEnv(env, "TELEGRAM_BOT_TOKEN");
  const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Telegram ${method} failed: ${response.status} ${await response.text()}`);
  }
  return response.json();
}

async function sendTelegramText(env, text) {
  const chatId = getRequiredEnv(env, "TELEGRAM_CHAT_ID");
  return callTelegram(env, "sendMessage", {
    chat_id: chatId,
    text,
  });
}

function isAllowedChat(env, message) {
  const chatId = String(message?.chat?.id || "");
  return chatId && chatId === String(env.TELEGRAM_CHAT_ID || "");
}

async function dispatchLoginWorkflow(env) {
  const repo = getRequiredEnv(env, "GITHUB_REPOSITORY");
  const token = getRequiredEnv(env, "GITHUB_TOKEN");
  const workflow = env.GITHUB_LOGIN_WORKFLOW || "wxread-login.yml";
  const ref = env.GITHUB_REF || "main";
  const commandId = crypto.randomUUID();
  const response = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
        "user-agent": "wxread-telegram-worker",
        "x-github-api-version": "2022-11-28",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          command_id: commandId,
          source: "telegram",
        },
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`GitHub workflow dispatch failed: ${response.status} ${await response.text()}`);
  }
  return commandId;
}

async function handleCommand(env, message) {
  const rawText = String(message.text || "").trim();
  const command = rawText.split(/\s+/, 1)[0].split("@", 1)[0].toLowerCase();

  if (!isAllowedChat(env, message)) {
    return jsonResponse({ ok: true, ignored: "chat_not_allowed" });
  }

  if (command === "/start" || command === "/help") {
    await sendTelegramText(
      env,
      "📚 微信读书自动恢复命令：\n\n/wxread_login  🚀 启动登录恢复\n/wxread_refresh  🔄 刷新二维码\n/wxread_status   📊 查看状态\n/wxread_cancel   ❌ 取消",
    );
    return jsonResponse({ ok: true });
  }

  if (command === "/wxread_login") {
    await putState(env, {
      status: "dispatching",
      refreshRequestedAt: null,
      cancelRequestedAt: null,
      runId: null,
      lastMessage: "正在触发 GitHub 登录恢复 workflow。",
    });
    const commandId = await dispatchLoginWorkflow(env);
    await putState(env, {
      status: "starting",
      commandId,
      lastMessage: "已触发 GitHub 登录恢复 workflow，等待二维码生成。",
    });
    await sendTelegramText(env, "🚀 已启动微信读书登录恢复任务，稍后会发送二维码。");
    return jsonResponse({ ok: true, commandId });
  }

  if (command === "/wxread_refresh") {
    const state = await putState(env, {
      refreshRequestedAt: new Date().toISOString(),
      lastMessage: "已收到二维码刷新请求。",
    });
    await sendTelegramText(env, "🔄 已收到刷新请求，登录恢复任务会重新发送二维码。");
    return jsonResponse({ ok: true, state });
  }

  if (command === "/wxread_status") {
    const state = await getState(env);
    await sendTelegramText(
      env,
      `📊 微信读书登录恢复状态：${state.status}\n\n${state.lastMessage || "暂无状态详情。"}\n\n更新时间：${state.updatedAt}`,
    );
    return jsonResponse({ ok: true, state });
  }

  if (command === "/wxread_cancel") {
    const state = await putState(env, {
      status: "cancel_requested",
      cancelRequestedAt: new Date().toISOString(),
      lastMessage: "已收到取消请求。",
    });
    await sendTelegramText(env, "❌ 已收到取消请求，登录恢复任务会停止。");
    return jsonResponse({ ok: true, state });
  }

  return jsonResponse({ ok: true, ignored: "unknown_command" });
}

async function handleTelegramWebhook(request, env) {
  const update = await request.json();
  const message = update.message || update.edited_message;
  if (!message?.text) {
    return jsonResponse({ ok: true, ignored: "no_text_message" });
  }
  return handleCommand(env, message);
}

function assertControlToken(request, env) {
  const expected = getRequiredEnv(env, "WXREAD_RECOVERY_CONTROL_TOKEN");
  const actual = request.headers.get("x-wxread-token") || new URL(request.url).searchParams.get("token");
  if (!actual || actual !== expected) {
    return false;
  }
  return true;
}

async function handleStateApi(request, env) {
  if (!assertControlToken(request, env)) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }
  if (request.method === "GET") {
    return jsonResponse({ ok: true, state: await getState(env) });
  }
  if (request.method === "POST") {
    const patch = await request.json();
    return jsonResponse({ ok: true, state: await putState(env, patch) });
  }
  return jsonResponse({ ok: false, error: "method_not_allowed" }, 405);
}

async function handleSetCommands(request, env) {
  if (!assertControlToken(request, env)) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }
  const result = await callTelegram(env, "setMyCommands", {
    commands: COMMANDS,
  });
  return jsonResponse({ ok: true, result });
}

async function handleSetWebhook(request, env) {
  if (!assertControlToken(request, env)) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }
  const url = new URL(request.url);
  const webhookSecret = getRequiredEnv(env, "WEBHOOK_SECRET");
  const webhookUrl = `${url.origin}/telegram/${webhookSecret}`;
  const result = await callTelegram(env, "setWebhook", {
    url: webhookUrl,
    allowed_updates: ["message", "edited_message"],
  });
  return jsonResponse({ ok: true, webhookUrl, result });
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "POST" && url.pathname === `/telegram/${env.WEBHOOK_SECRET}`) {
        return handleTelegramWebhook(request, env);
      }
      if (url.pathname === "/api/state") {
        return handleStateApi(request, env);
      }
      if (request.method === "POST" && url.pathname === "/admin/set-commands") {
        return handleSetCommands(request, env);
      }
      if (request.method === "POST" && url.pathname === "/admin/set-webhook") {
        return handleSetWebhook(request, env);
      }
      return jsonResponse({
        ok: true,
        service: "wxread-telegram-worker",
      });
    } catch (error) {
      return jsonResponse(
        {
          ok: false,
          error: error.message,
        },
        500,
      );
    }
  },
};
