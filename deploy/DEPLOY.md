# Deploying the YouTube connector MCP server

The connector runs as a third process inside the existing Spark ECS task,
exactly like the messaging service: `start.sh` launches
`python -m youtube_mcp.server` (port 8000) with the same restart-loop pattern.
Muse (and any MCP client) talks to it at `https://youtube.1xaispark.com/mcp`
(streamable HTTP). `GET /healthz` is an unauthenticated liveness probe for the
ALB target-group health check.

**Cost: $0 extra.** Same task, same ALB, no new service. The only new AWS
pieces are a target group + host-based listener rule + one Route53 record,
all on infrastructure already in place.

## 1. What the Spark repo changes contain

- `Dockerfile`: new `youtube-mcp` stage pip-installs the connector from the
  private `deepujain/youtube-mcp` repo into `/app/mcp-deps` (BuildKit secret
  `github_token`, never baked into the image); runner stage adds `python3`
  and copies `/app/mcp-deps`.
- `start.sh`: launches the MCP server with `YOUTUBE_HOST=0.0.0.0`
  (the ALB reaches the task ENI IP, not localhost),
  `PYTHONPATH=/app/mcp-deps`, restart-on-crash loop, and SIGTERM handling.

## 2. Build

The connector install needs a GitHub token with read access to the private
`deepujain/youtube-mcp` repo, passed as a BuildKit secret (add to `deploy.sh`):

```bash
DOCKER_BUILDKIT=1 docker build \
  --secret id=github_token,src=$HOME/.github-token \
  -t $ECR/spark:$TAG .
```

## 3. One-time AWS setup (console or CLI)

1. **Secret:** `YOUTUBE_API_KEY` (restricted to YouTube Data API v3, project
   `spark-e2e54`) in AWS Secrets Manager.
2. **Task definition** (`spark-task` revision): add container port mapping
   `8000/tcp`; add the secret as `YOUTUBE_API_KEY` env var. No CPU/memory
   bump needed — the server idles near zero.
3. **Target group:** port 8000, health check path `/healthz` expecting
   HTTP 200, registered against the `spark-web` ECS service tasks.
4. **ALB listener rule:** host `youtube.1xaispark.com` → the new target group
   (port 8000).
5. **Route53:** A/alias record `youtube.1xaispark.com` → the ALB.

Security group: the task already allows ALB → task; ensure the rule covers
port 8000 (or all task ports).

## 4. Public URL contract

```
https://youtube.1xaispark.com/mcp
```

That URL goes into the Meta connector submission form as the hosted MCP
endpoint, and on the 1xaispark.com/connectors listing page. Treat it as
permanent — the hostname is the contract with users; the process behind it
can move freely later without breaking anyone.

## 5. Operational notes

- **Quota:** YouTube Data API v3 default quota is 10,000 units/day per
  Google Cloud project. `search` costs 100 units; everything else here costs
  1–50. `catch_me_up` deliberately avoids `search` (~1 unit/channel).
  Watch quota in Google Cloud Console → APIs → YouTube Data API v3.
- **Logs:** no tokens, video content, or credentials are logged — only
  operational metadata (timestamps, error codes).
- **OAuth consent screen** stays in Google "Testing" mode (publishing with
  the sensitive `youtube.force-ssl` scope would require Google verification).
  In Testing mode each user must be added as a test user in the Cloud
  console until verification is pursued.
- **Stripping out later:** revert the Dockerfile/`start.sh` edits, drop port
  8000 + the secret from the task definition, delete the ALB rule and DNS
  record. Pending write-approvals (in-memory, 10-min TTL) are the only thing
  lost in a move — users just re-issue the action.
