const OWNER = "alonmorad9";
const REPO = "tqqq-alert";
const WORKFLOW_FILE = "main.yml";

async function triggerWorkflow(env, schedule = "") {
  console.log("Dispatching GitHub workflow", {
    owner: OWNER,
    repo: REPO,
    workflow: WORKFLOW_FILE,
    schedule,
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
        inputs: {
          mode: "auto",
          schedule,
        },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    console.error("GitHub dispatch failed", {
      status: response.status,
      body,
      schedule,
    });
    throw new Error(`GitHub dispatch failed: ${response.status} ${body}`);
  }

  console.log("GitHub dispatch succeeded", {
    status: response.status,
    schedule,
  });
}

export default {
  async scheduled(event, env, ctx) {
    console.log("Scheduled trigger fired", {
      cron: event.cron,
      scheduledTime: event.scheduledTime,
    });
    ctx.waitUntil(triggerWorkflow(env, event.cron));
  },

  async fetch(request, env) {
    console.log("Manual trigger received", {
      method: request.method,
      url: request.url,
    });

    if (request.method !== "POST") {
      return new Response("Use POST to trigger the workflow.\n", { status: 405 });
    }

    await triggerWorkflow(env);
    return new Response("Triggered TQQQ alert workflow.\n");
  },
};
