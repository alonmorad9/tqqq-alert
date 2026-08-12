const OWNER = "alonmorad9";
const REPO = "tqqq-alert";
const WORKFLOW_FILE = "main.yml";
const SWING_REPO = "swing-tracker-new";
const SWING_WORKFLOW_FILE = "daily-sync.yml";
const SWING_TRADES_PATH = "data/trades.json";
const MARKET_OPEN_MINUTE_UTC = 13 * 60 + 30;
const MARKET_CLOSE_MINUTE_UTC = 20 * 60;

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

async function triggerSwingWorkflow(env) {
  console.log("Dispatching swing tracker workflow", {
    owner: OWNER,
    repo: SWING_REPO,
    workflow: SWING_WORKFLOW_FILE,
  });

  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${SWING_REPO}/actions/workflows/${SWING_WORKFLOW_FILE}/dispatches`,
    {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "tqqq-alert-scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main" }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    console.error("Swing GitHub dispatch failed", {
      status: response.status,
      body,
    });
    throw new Error(`Swing GitHub dispatch failed: ${response.status} ${body}`);
  }

  console.log("Swing GitHub dispatch succeeded", { status: response.status });
}

async function readGitHubJson(env, repo, path) {
  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${repo}/contents/${path}?ref=main`,
    {
      headers: {
        "Accept": "application/vnd.github.raw+json",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "User-Agent": "tqqq-alert-scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    },
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub read failed for ${repo}/${path}: ${response.status} ${body}`);
  }
  return response.json();
}

async function fetchYahooQuote(symbol) {
  const response = await fetch(
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1d&interval=1m`,
    {
      headers: {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 tqqq-alert-scheduler",
      },
    },
  );
  if (!response.ok) throw new Error(`Yahoo quote failed for ${symbol}: ${response.status}`);
  const body = await response.json();
  const result = body?.chart?.result?.[0];
  const quote = result?.indicators?.quote?.[0];
  const closes = (quote?.close || []).filter((v) => typeof v === "number" && isFinite(v));
  const highs = (quote?.high || []).filter((v) => typeof v === "number" && isFinite(v));
  const timestamps = result?.timestamp || [];
  const price = closes.length ? closes[closes.length - 1] : null;
  const dayHigh = highs.length ? Math.max(...highs) : price;
  const lastTs = timestamps.length ? timestamps[timestamps.length - 1] : null;
  if (price == null) throw new Error(`Yahoo quote returned no price for ${symbol}`);
  return {
    price,
    dayHigh: dayHigh ?? price,
    source: lastTs ? `Yahoo 1m ${new Date(lastTs * 1000).toISOString()}` : "Yahoo 1m",
  };
}

function isWeekday(now = new Date()) {
  const day = now.getUTCDay();
  return day >= 1 && day <= 5;
}

function isMarketWindow(now = new Date()) {
  if (!isWeekday(now)) return false;
  const minute = now.getUTCHours() * 60 + now.getUTCMinutes();
  return minute >= MARKET_OPEN_MINUTE_UTC && minute <= MARKET_CLOSE_MINUTE_UTC;
}

function manualLadderStopDue(trade, quote) {
  const ladder = Array.isArray(trade.ladder) ? trade.ladder : [];
  const currentStop = typeof trade.stop === "number" && isFinite(trade.stop) ? trade.stop : null;
  const ref = Math.max(
    Number(trade.peakPrice) || 0,
    Number(trade.entry) || 0,
    quote.price || 0,
    quote.dayHigh || 0,
  );
  const hit = ladder
    .filter((stage) => stage && typeof stage.price === "number" && typeof stage.stop === "number")
    .filter((stage) => ref >= stage.price)
    .filter((stage) => currentStop == null || stage.stop > currentStop + 0.01);
  if (!hit.length) return null;
  const best = hit.reduce((max, stage) => stage.stop > max.stop ? stage : max, hit[0]);
  return { ...best, ref, currentStop };
}

async function wasRecentlyAlerted(request) {
  const cached = await caches.default.match(request);
  return Boolean(cached);
}

async function markRecentlyAlerted(request) {
  await caches.default.put(
    request,
    new Response("alerted", {
      headers: {
        "Cache-Control": "public, max-age=28800",
      },
    }),
  );
}

async function checkSwingStopLadders(env, options = {}) {
  const alertChatId = options.chatId || env.TELEGRAM_CHAT_ID;
  if (!alertChatId) {
    console.log("Skipping swing stop monitor: TELEGRAM_CHAT_ID Cloudflare secret missing");
    return { checked: 0, alerts: 0, skipped: "missing_chat_id" };
  }
  if (!options.force && !isMarketWindow()) {
    return { checked: 0, alerts: 0, skipped: "market_closed" };
  }

  const trades = await readGitHubJson(env, SWING_REPO, SWING_TRADES_PATH);
  const openTrades = Array.isArray(trades) ? trades.filter((trade) => trade && trade.ticker) : [];
  let checked = 0;
  let alerts = 0;

  for (const trade of openTrades) {
    const ladder = Array.isArray(trade.ladder) ? trade.ladder : [];
    if (!ladder.some((stage) => typeof stage?.price === "number" && typeof stage?.stop === "number")) continue;
    checked++;

    try {
      const quote = await fetchYahooQuote(trade.ticker);
      const due = manualLadderStopDue(trade, quote);
      if (!due) continue;

      const key = `${trade.id || trade.ticker}:${trade.ticker}:${due.stop.toFixed(2)}:${new Date().toISOString().slice(0, 10)}`;
      const cacheRequest = new Request(`https://tqqq-alert-scheduler.local/swing-stop-alert/${encodeURIComponent(key)}`);
      if (!options.force && await wasRecentlyAlerted(cacheRequest)) continue;

      const lines = [
        `🚨 Swing Stop Update — ${trade.ticker}`,
        "──────────────────────────────",
        "Action: RAISE STOP",
        "Why: your manual stop-ladder trigger was reached intraday.",
        "Advisory only: update the broker manually, then update the tracker stop.",
        "──────────────────────────────",
        `Price:        $${quote.price.toFixed(2)}`,
        `Day high/ref: $${due.ref.toFixed(2)}`,
        `Trigger hit:  ${due.stage || "ladder stage"} at $${due.price.toFixed(2)}`,
        `Old stop:     ${due.currentStop == null ? "not set" : "$" + due.currentStop.toFixed(2)}`,
        `New stop:     $${due.stop.toFixed(2)}`,
        `Source:       ${quote.source}`,
        "──────────────────────────────",
        `Broker action: move ${trade.ticker} stop to $${due.stop.toFixed(2)}.`,
      ];
      await sendTelegram(env, alertChatId, lines.join("\n"));
      await markRecentlyAlerted(cacheRequest);
      alerts++;
    } catch (error) {
      console.error(`Swing stop monitor failed for ${trade.ticker}:`, error.message);
    }
  }

  return { checked, alerts };
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
    "/swing — run swing trade digest",
    "/swingstops — check swing stop ladders now",
    "/whoami — show this Telegram chat id",
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

async function setTelegramWebhook(env, requestUrl) {
  if (!env.TELEGRAM_TOKEN) {
    return new Response("Missing Cloudflare secret TELEGRAM_TOKEN.\n", { status: 500 });
  }

  const url = new URL(requestUrl);
  url.pathname = "/";
  url.search = "";

  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/setWebhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: url.toString(),
      allowed_updates: ["message", "edited_message", "callback_query"],
    }),
  });

  const body = await response.text();
  return new Response(`${body}\n`, { status: response.ok ? 200 : 500 });
}

async function handleTelegramUpdate(update, env) {
  if (update.callback_query) {
    const callback = update.callback_query;
    const data = callback.data || "";
    const chatId = callback.message?.chat?.id;
    if (data === "confirm_buy") {
      await answerCallback(env, callback.id, "Exact broker fill required.");
      await sendTelegram(env, chatId, "The bot no longer records real buys at the signal price.\n\nAfter your broker order fills, send:\n/bought PRICE SHARES\n\nExample:\n/bought 75.30 13.2802");
      return new Response("ok\n");
    }
    if (data === "confirm_sell") {
      await answerCallback(env, callback.id, "Exact broker fill required.");
      await sendTelegram(env, chatId, "The bot no longer records real sells at the signal price.\n\nAfter your broker order fills, send:\n/sold PRICE\n\nExample:\n/sold 82.10");
      return new Response("ok\n");
    }
    if (data === "help_bought") {
      await answerCallback(env, callback.id, "Sent exact buy-fill help.");
      await sendTelegram(env, chatId, "Sync buy fill:\nRecords your exact broker buy price and share count, then queues a fresh status report.\n\nSend:\n/bought PRICE SHARES\n\nExample:\n/bought 75.30 13.2802");
      return new Response("ok\n");
    }
    if (data === "help_sold") {
      await answerCallback(env, callback.id, "Sent exact sell-fill help.");
      await sendTelegram(env, chatId, "Sync sell fill:\nRecords your exact broker sell price, moves the real state to cash/manual safety mode, then queues a fresh status report.\n\nSend:\n/sold PRICE\n\nExample:\n/sold 82.10");
      return new Response("ok\n");
    }
    if (data === "help_cash") {
      await answerCallback(env, callback.id, "Sent cash sync help.");
      await sendTelegram(env, chatId, "To sync the TQQQ cash bucket, send:\n/cash AMOUNT\n\nExample:\n/cash 1000");
      return new Response("ok\n");
    }
    if (data === "help_buttons") {
      await answerCallback(env, callback.id, "Sent button help.");
      await sendTelegram(
        env,
        chatId,
        [
          "Button help:",
          "",
          "📊 Daily report: sends a full status report now, even if there is no buy/sell signal.",
          "🔎 Check now: sends a compact result every time. If there is no signal, it explains the current blocker.",
          "📈 Swing digest: runs the swing tracker Daily Sync and sends Swing Actions/Daily Digest to this chat.",
          "🚨 Swing stops: immediately checks whether your manual stop ladders need broker updates.",
          "✏️ Sync buy fill: shows /bought PRICE SHARES. Use it after the broker buy fills.",
          "✏️ Sync sell fill: shows /sold PRICE. Use it after the broker sell fills.",
          "💵 Cash sync help: shows how to update tracked cash.",
          "",
          "Important: BUY/SELL signals do not update your real tracked position automatically. Only exact-fill sync commands update real state.",
          "",
          "Weekly report: not active in this TQQQ swing bot right now. This bot uses opening/closing full reports plus 10-minute signal checks.",
        ].join("\n")
      );
      return new Response("ok\n");
    }
    if (data === "run_daily") {
      await triggerWorkflow(env, { mode: "daily" });
      await answerCallback(env, callback.id, "Queued daily report.");
      await sendTelegram(env, chatId, "Queued 📊 Daily report. It should arrive after GitHub Actions finishes.");
      return new Response("queued\n");
    }
    if (data === "run_check") {
      await triggerWorkflow(env, { mode: "check" });
      await answerCallback(env, callback.id, "Queued signal check.");
      await sendTelegram(env, chatId, "Queued 🔎 Check now. A compact result should arrive after GitHub Actions finishes.");
      return new Response("queued\n");
    }
    if (data === "run_swing_daily") {
      await triggerSwingWorkflow(env);
      await answerCallback(env, callback.id, "Queued swing digest.");
      await sendTelegram(env, chatId, "Queued 📈 Swing digest. It should arrive after the swing tracker Daily Sync finishes.");
      return new Response("queued\n");
    }
    if (data === "run_swing_stops") {
      const result = await checkSwingStopLadders(env, { force: true, chatId });
      await answerCallback(env, callback.id, `Swing stops checked: ${result.alerts || 0} alert(s).`);
      await sendTelegram(env, chatId, `Checked 🚨 Swing stops now: ${result.checked || 0} ladder trade(s), ${result.alerts || 0} alert(s).`);
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

  if (text.startsWith("/whoami")) {
    await sendTelegram(
      env,
      chatId,
      [
        "Telegram chat info:",
        `chat.id: ${chatId}`,
        `chat.type: ${message?.chat?.type || "unknown"}`,
        "",
        "Use chat.id as TELEGRAM_CHAT_ID in the swing tracker GitHub repo and the Cloudflare worker.",
      ].join("\n")
    );
    return new Response("ok\n");
  }

  if (text.startsWith("/swingstops")) {
    const result = await checkSwingStopLadders(env, { force: true, chatId });
    await sendTelegram(env, chatId, `Checked 🚨 Swing stops now: ${result.checked || 0} ladder trade(s), ${result.alerts || 0} alert(s).`);
    return new Response("ok\n");
  }

  if (text.startsWith("/swing")) {
    await triggerSwingWorkflow(env);
    await sendTelegram(env, chatId, "Queued 📈 Swing digest. It should arrive after the swing tracker Daily Sync finishes.");
    return new Response("queued\n");
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
    ctx.waitUntil(Promise.allSettled([
      triggerWorkflow(env, { mode: "auto", schedule: event.cron }),
      checkSwingStopLadders(env),
    ]));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    console.log("Request received", {
      method: request.method,
      url: request.url,
    });

    if (request.method === "POST" && url.pathname === "/setup-webhook") {
      return setTelegramWebhook(env, request.url);
    }

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
