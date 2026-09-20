# Deploying the YouTube connector MCP server

The connector is a stateless HTTP service. Muse (and any MCP client) talks to
it at `https://<your-host>/mcp` (streamable HTTP). `GET /healthz` is an
unauthenticated liveness probe for the load balancer / ECS health check.

## 1. Secrets

| Variable | Required | Notes |
|---|---|---|
| `YOUTUBE_API_KEY` | yes | API key restricted to YouTube Data API v3 (Google Cloud project `spark-e2e54`). Inject via AWS Secrets Manager / ECS `secrets`, never in the image or repo. |
| `YOUTUBE_OAUTH_TOKEN` | no (dev only) | Leave unset in production. Per-user OAuth tokens are supplied by the connector platform's credential flow at connect time; a server-wide token would act as every user at once. Private tools return a helpful "complete the OAuth flow" error when no token is present. |

`deploy/.env.example` documents every variable the server reads.

## 2. Build & push (ECR)

```bash
AWS_REGION=us-west-2          # or your region
AWS_ACCOUNT_ID=<account-id>
ECR=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

aws ecr create-repository --repository-name youtube-mcp --region $AWS_REGION || true
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR

docker build -t youtube-mcp:0.1.0 .
docker tag youtube-mcp:0.1.0 $ECR/youtube-mcp:0.1.0
docker push $ECR/youtube-mcp:0.1.0
```

## 3. Run (ECS Fargate sketch)

- Task: 0.25 vCPU / 0.5 GB, one container, port 8000, desired count 1.
  (Traffic is tiny; scale only if p95 latency degrades.)
- Environment: `YOUTUBE_HOST=0.0.0.0`, `YOUTUBE_PORT=8000`;
  `YOUTUBE_API_KEY` from Secrets Manager.
- ALB: HTTPS listener (ACM cert) → target group on port 8000 with
  health check path `/healthz` expecting HTTP 200.
- Security group: ALB → task on 8000 only; task egress to
  `https://www.googleapis.com` (443).

Any equivalent (single small VM, Cloud Run, App Runner) works — the server
has no local state: pending write-approvals live in memory and expire in
10 minutes by default.

## 4. Public URL contract

After deploy, the endpoint Muse connects to is:

```
https://youtube.1xaispark.com/mcp
```

(The eBay connector follows the same pattern: `https://ebay.1xaispark.com/mcp`.)
That URL goes into the Meta connector submission form as the hosted MCP
endpoint, and on the 1xaispark.com/connectors listing page.

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
