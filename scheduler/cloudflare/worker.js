const OWNER = "alonmorad9";
const REPO = "tqqq-alert";
const WORKFLOW_FILE = "main.yml";

async function triggerWorkflow(env, inputs = {}) {
  const workflowInputs = {
    mode: inputs.mode || "auto",
    schedule: inputs.schedule || "",
    manual_price: inputs.manual_price || "",
    manual_amount: inputs.manual_amount || "",
    manual_shares: inputs.manual_shares || "",
  };

  console.log("Dispatching GitHub workflow", {
    owner: OWNER,
    repo: REPO,
    workflow: WORKFLOW_FILE,
    inputs: workflowInputs,
  });

  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "tqqq-alert-scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: workflowInputs,
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    console.error("GitHub dispatch failed", {
      status: response.status,
      body,
      inputs: workflowInputs,
    });
    throw new Error(`GitHub dispatch failed: ${response.status} ${body}`);
  }

  console.log("GitHub dispatch succeeded", {
    status: response.status,
    inputs: workflowInputs,
  });
}

function parseTelegramCommand(text = "") {
  const parts = text.trim().split(/\s+/);
  const command = (parts[0] || "").split("@")[0].toLowerCase();

  if (command === "/bought") {
    return {
      mode: "manual_bought",
      manual_price: parts[1] || "",
      manual_shares: parts[2] || "",
    };
  }

  if (command === "/sold") {
    return {
      mode: "manual_sold",
      manual_price: parts[1] || "",
    };
  }

  if (command === "/cash") {
    return {
      mode: "manual_cash_set",
      manual_amount: parts[1] || "",
    };
  }

  if (command === "/daily") {
    return { mode: "daily" };
  }

  if (command === "/check") {
    return { mode: "check" };
  }

  return null;
}

function commandHelp() {
  return [
    "TQQQ bot commands:",
    "/bought PRICE SHARES — sync exact broker buy",
    "/sold PRICE — sync exact broker sell",
    "/cash AMOUNT — sync cash bucket",
    "/daily — send full report",
    "/check — run signal check",
  ].join("\n");
}

async function sendTelegram(env, chatId, text) {
  if (!env.TELEGRAM_TOKEN || !chatId) {
    console.log("Skipping Telegram response: TELEGRAM_TOKEN or chatId missing");
    return;
  }

  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

async function answerCallback(env, callbackQueryId, text) {
  if (!env.TELEGRAM_TOKEN || !callbackQueryId) {
    console.log("Skipping callback answer: TELEGRAM_TOKEN or callback id missing");
    return;
  }

  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/answerCallbackQuery`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      callback_query_id: callbackQueryId,
      text,
      show_alert: false,
    }),
  });
}

async function handleTelegramUpdate(update, env) {
  if (update.callback_query) {
    const callback = update.callback_query;
    const data = callback.data || "";
    if (data === "confirm_buy") {
      await answerCallback(env, callback.id, "Confirmed. Bot already tracks the buy at its signal price.");
      return new Response("ok\n");
    }
    if (data === "confirm_sell") {
      await answerCallback(env, callback.id, "Confirmed. Bot already tracks the sell at its signal price.");
      return new Response("ok\n");
    }
    if (data === "help_bought") {
      await answerCallback(env, callback.id, "Send: /bought PRICE SHARES");
      return new Response("ok\n");
    }
    if (data === "help_sold") {
      await answerCallback(env, callback.id, "Send: /sold PRICE");
      return new Response("ok\n");
    }
  }

  const message = update.message || update.edited_message;
  const text = message?.text || "";
  const chatId = message?.chat?.id;

  if (!text.startsWith("/")) {
    return new Response("ignored\n");
  }

  if (text.startsWith("/help") || text.startsWith("/start")) {
    await sendTelegram(env, chatId, commandHelp());
    return new Response("ok\n");
  }

  const inputs = parseTelegramCommand(text);
  if (!inputs) {
    await sendTelegram(env, chatId, commandHelp());
    return new Response("unknown command\n");
  }

  if ((inputs.mode === "manual_bought" || inputs.mode === "manual_sold") && !inputs.manual_price) {
    await sendTelegram(env, chatId, "Missing price. Example: /bought 75.30 13.2802 or /sold 82.10");
    return new Response("missing price\n");
  }

  if (inputs.mode === "manual_cash_set" && !inputs.manual_amount) {
    await sendTelegram(env, chatId, "Missing amount. Example: /cash 1000");
    return new Response("missing amount\n");
  }

  await triggerWorkflow(env, inputs);
  await sendTelegram(env, chatId, `Queued GitHub sync: ${inputs.mode}`);
  return new Response("queued\n");
}

export default {
  async scheduled(event, env, ctx) {
    console.log("Scheduled trigger fired", {
      cron: event.cron,
      scheduledTime: event.scheduledTime,
    });
    ctx.waitUntil(triggerWorkflow(env, { mode: "auto", schedule: event.cron }));
  },

  async fetch(request, env) {
    console.log("Request received", {
      method: request.method,
      url: request.url,
    });

    if (request.method !== "POST") {
      return new Response("Use POST to trigger the workflow or Telegram webhook.\n", { status: 405 });
    }

    const contentType = request.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const update = await request.json();
      if (update.message || update.edited_message || update.callback_query) {
        return handleTelegramUpdate(update, env);
      }
    }

    await triggerWorkflow(env, { mode: "auto" });
    return new Response("Triggered TQQQ alert workflow.\n");
  },
};
