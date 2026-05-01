# External Scheduler Fallback

GitHub Actions scheduled workflows are best effort. If native `schedule` runs are delayed or dropped, use an external scheduler to call the workflow's `workflow_dispatch` endpoint.

The workflow already supports this with:

```json
{
  "ref": "main",
  "inputs": {
    "mode": "auto"
  }
}
```

## Cloudflare Worker Cron

The starter worker lives in `scheduler/cloudflare`.

1. Create a GitHub fine-grained token with access to this repository and permission to run Actions workflows.
2. From `scheduler/cloudflare`, set the token as a secret:

```bash
npx wrangler secret put GITHUB_TOKEN
```

3. Deploy:

```bash
npx wrangler deploy
```

The worker has two cron triggers:

```text
*/10 13-21 * * MON-FRI
45 13-20 * * MON-FRI
```

Those are UTC times. Cloudflare treats weekday numbers differently from GitHub, so use `MON-FRI` instead of `1-5`. The Python script still filters by the real NASDAQ session, so extra candidates outside trading hours should safely skip.

## Direct API Call

Any external scheduler that can send an authenticated POST can use this request:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/alonmorad9/tqqq-alert/actions/workflows/main.yml/dispatches \
  -d '{"ref":"main","inputs":{"mode":"auto"}}'
```

Use the same schedule candidates as above.
