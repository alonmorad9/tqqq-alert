const OWNER = "alonmorad9";
const REPO = "tqqq-alert";
const WORKFLOW_FILE = "main.yml";

async function triggerWorkflow(env, schedule = "") {
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
    throw new Error(`GitHub dispatch failed: ${response.status} ${await response.text()}`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerWorkflow(env, event.cron));
  },

  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Use POST to trigger the workflow.\n", { status: 405 });
    }

    await triggerWorkflow(env);
    return new Response("Triggered TQQQ alert workflow.\n");
  },
};
