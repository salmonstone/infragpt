# InfraGPT

Production-ready AI DevOps Q&A API built with FastAPI, Groq LLM, Redis, PostgreSQL, and deployed on AWS EKS.

## Architecture

```
Users → Nginx Ingress (LB) → FastAPI Pods (HPA 2-6) → Redis (cache + rate-limit)
                                                      → PostgreSQL (users + chat history)
                                                      → Groq LLM API (with retry + fallback)
                                       ↓
                              Prometheus /metrics → Grafana
                              Filebeat sidecar   → ELK Stack (Kibana)
```

Two diagrams are included in the repo root:
- [`infragpt_runtime_architecture.svg`](infragpt_runtime_architecture.svg) — the **request-path** diagram above, rendered: `Users → LB → FastAPI (HPA) → Redis / PostgreSQL → LLM Gateway → Groq API`, plus the observability/logging branch and where a background queue and circuit breaker fit at higher scale.
- [`infragpt_architecture.svg`](infragpt_architecture.svg) — the **CI/CD pipeline** diagram: GitHub → Jenkins (build, Trivy scan, push) → Terraform (EKS/VPC) → Helm deploy.

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | No | Get JWT token |
| POST | `/auth/register` | No | Self-service signup — always creates role `user`; role can't be set by the client |
| POST | `/chat` | JWT | Ask a DevOps question |
| GET | `/health` | No | Health check |
| GET | `/metrics` | No | Prometheus metrics |
| GET | `/history` | JWT | **Your own** chat history — always, including for admins |
| GET | `/admin/users` | JWT (admin) | List all registered users |
| GET | `/admin/users/{username}/history` | JWT (admin) | View one specific user's chat history |
| PATCH | `/admin/users/{username}/role` | JWT (admin) | Change a user's role (blocks demoting the last admin) |
| GET | `/` | No | Web UI |

Chat isolation is enforced server-side by filtering every query on the JWT's own username — never by anything the client sends. Admin seeing "everyone's chats by default" isn't a thing here on purpose: `/history` is deliberately just-yours-always, and cross-user visibility only exists as the separate, explicit `/admin/users/{username}/history` action.

`/chat` layers three lookups before generating anything new: Redis cache (5 min, fastest) → an exact-match lookup in Postgres (durable, reuses a previously-generated answer for the same question with zero new AI call) → only then a fresh Groq call, which is given the user's last 3 turns as conversation history so follow-ups ("explain that more") work instead of every message being treated as standalone.

## Authentication & Authorization

### Current implementation

JWT is implemented by hand in [`app/auth.py`](app/auth.py): HS256, signed with a shared `SECRET_KEY`, `sub` (username) + `role` + `exp` claims, verified with `hmac.compare_digest` to avoid timing attacks. `POST /auth/login` exchanges a username/password for a token; every protected route resolves the current user via `get_current_user` (a FastAPI dependency) and role checks are a one-line `require_role(...)` / inline `if current_user.role == ...`.

### Roles (RBAC)

| Role | `/chat` | `/history` | `/admin/users*` | `/metrics` | Intent |
|---|---|---|---|---|---|
| `admin` | ✅ Own history only | ✅ Own rows only | ✅ View any user's history, change roles | ✅ | Manage the platform — user administration and full metrics visibility, but no standing access to everyone's conversations |
| `user` | ✅ Own history only | ✅ (own rows) | ❌ | ✅ | The normal product user — can ask questions, cannot see other users' data |
| `readonly` | ❌ Blocked | ✅ | ❌ | ✅ | Auditors / support staff — can inspect reports and metrics, cannot spend LLM budget |

`readonly` exists specifically to separate *"can see data"* from *"can spend money calling the LLM"* — a common real-world split (e.g., a support engineer debugging a user's chat history shouldn't also be able to run up the Groq bill). Enforcement today is a single dependency per route (`require_role(...)`); at this scale that's the right amount of complexity — a full policy engine (OPA/Cedar) would be over-engineering for 3 roles and this route count, but is the natural next step if roles/resources multiply (see below).

Note `admin`'s `/history` is *own rows only*, same as everyone else — being an admin doesn't grant standing visibility into other users' conversations just by existing. Seeing someone else's history is a distinct, explicit, logged action (`GET /admin/users/{username}/history`), not a side effect of the role.

### Extending to production SSO / OIDC

Today the app *is* its own identity provider (it owns the `users` table and issues its own JWTs). The required production path:

```
Application → SSO / OAuth2 / OIDC → Identity Provider → JWT → API Gateway → AI Service
```

1. **Identity Provider (IdP)** — swap the local `users` table for a real IdP (Auth0, Okta, AWS Cognito, or Azure AD/Entra). Users authenticate against the IdP via the OIDC Authorization Code flow (with PKCE for any browser/SPA client); InfraGPT never sees a password.
2. **Token issuance** — the IdP issues the JWT (an OIDC ID token / access token), not our API. We stop signing tokens with a shared `SECRET_KEY` and switch verification from **HS256 (shared secret) to RS256/ES256 (asymmetric)** — the API validates signatures against the IdP's public JWKS endpoint (cached, rotated automatically), so no signing secret is shared with or stored by the app at all.
3. **Claims → RBAC mapping** — `admin` / `user` / `readonly` become **group or role claims** managed centrally in the IdP (e.g. an Okta group `infragpt-admins` mapped into a `roles` claim), instead of a column in our own DB. `require_role()` stays almost unchanged — it just reads `roles` off the validated token instead of a DB row.
4. **API Gateway** — an edge layer (Kong, AWS API Gateway, or an Envoy/Istio ingress) sits in front of the FastAPI pods and does token introspection/JWKS validation, coarse-grained rate limiting, and request logging *before* traffic reaches the app — so a malformed/expired token never costs a pod a database round-trip.
5. **Short-lived tokens + refresh** — access tokens get short TTLs (5–15 min) with silent refresh via the IdP, instead of today's 60-minute token with no revocation path. This bounds the blast radius of a leaked token.
6. **Service-to-service auth** — machine clients (CI, internal jobs calling `/chat`) get OAuth2 Client Credentials grants from the same IdP rather than a human-style login, so they're auditable and independently revocable.

The trade-off: this adds an external dependency (IdP uptime/latency) and infra cost, which isn't justified for a 3-role internal tool — it's justified once there's a real workforce/customer identity to federate, SSO is a compliance requirement, or roles need to be managed outside of a code deploy.

## Quick Start (Local)

```bash
# 1. Set your Groq API key
export GROQ_API_KEY=your_key_here

# 2. Start everything
docker compose up --build

# 3. Login and get token
curl -X POST http://localhost:5000/auth/login \
  -d "username=admin&password=admin123"

# 4. Chat
curl -X POST http://localhost:5000/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I scale an EKS cluster?"}'
```

Default users seeded on first start (only when the `users` table is empty):
- `admin` / `admin123` (role: admin)
- `user1` / `user123` (role: user)

These are **local-dev defaults only**, not hard-coded secrets — they live in [`app/config.py`](app/config.py) as `seed_admin_username` / `seed_admin_password` / `seed_user_username` / `seed_user_password` and are overridden via env vars (or Kubernetes secrets) in any shared environment:
```bash
export SEED_ADMIN_PASSWORD=$(openssl rand -base64 24)
export SEED_USER_PASSWORD=$(openssl rand -base64 24)
```
Passwords are hashed with bcrypt ([`app/auth.py`](app/auth.py)) before being stored.

## Run Tests

Install the **pinned** app dependencies (plus `pytest`) rather than latest — `fastapi`/`httpx`/`groq` are version-sensitive together, and installing them unpinned can hit resolver conflicts unrelated to the app itself:

```bash
pip install -r app/requirements.txt pytest
cd tests
pytest test_api.py -v
```

All 7 tests exercise real request/response behavior against the FastAPI app — DB and JWT-identity dependencies are swapped via FastAPI's `app.dependency_overrides` (not `unittest.mock.patch`, which can't reach a dependency already bound into a route by `Depends(...)`), so e.g. the RBAC and empty-message tests actually fail if that logic breaks, rather than passing on a coincidental early error.

## Production Deployment (AWS EKS)

Jenkins pipeline handles:
1. Docker build + Trivy scan → DockerHub
2. Terraform — EKS cluster, VPC, EBS CSI driver
3. Helm deploy — app + Postgres + Redis + HPA + PDB + Ingress + TLS (Let's Encrypt)
4. ELK Stack — Elasticsearch, Logstash, Kibana, Filebeat sidecar

Postgres and Redis run as in-cluster pods ([`helm/infragpt/templates/postgres.yaml`](helm/infragpt/templates/postgres.yaml), [`helm/infragpt/templates/redis.yaml`](helm/infragpt/templates/redis.yaml)) rather than managed AWS services — the cheaper, faster-to-stand-up option for this deployment, at the cost of no HA/backups and data not surviving a PVC/cluster teardown. Swapping either for RDS/ElastiCache later is a one-line change (point `DATABASE_URL`/`REDIS_URL` at the managed endpoint instead) since the app only talks to them over a connection string — see the trade-off called out in the *Migration* section above for when that swap is worth making.

Required Jenkins credentials (Secret text), beyond the existing `dockerhub-creds` and `groq-api-key`:
- `jwt-secret-key` — signs JWTs; generate with `openssl rand -hex 32`
- `postgres-db-password` — the in-cluster Postgres password

```bash
# Manual Helm deploy
helm upgrade --install infragpt ./helm/infragpt \
  --namespace infragpt \
  --set image.tag=<BUILD_NUMBER>
```

## Scaling Scenario — 100 RPS, bursting to 500 RPS

See [`infragpt_runtime_architecture.svg`](infragpt_runtime_architecture.svg) for the request-path diagram this section describes. Design decisions and the trade-off behind each:

- **Horizontal scaling.** The app is stateless — no in-memory session or sticky state, all shared state lives in Redis/Postgres — so scaling is purely "add more FastAPI pods." That statelessness is *why* HPA works at all; it's the one non-negotiable property of the design.
- **Load balancing.** Nginx Ingress terminates TLS and distributes across pods at L7; the Kubernetes `Service` load-balances across ready endpoints. Readiness/liveness probes hit `GET /health` ([`k8s/deployment.yaml`](k8s/deployment.yaml)) so a pod that's still booting or wedged is pulled out of rotation automatically — traffic never reaches a pod that can't serve it.
- **Kubernetes HPA.** 2 → 6 pods, triggered at 60% CPU / 70% memory ([`k8s/deployment.yaml`](k8s/deployment.yaml), [`helm/infragpt/values.yaml`](helm/infragpt/values.yaml)), with a 60s scale-up / 300s scale-down stabilization window so it reacts fast to a burst but doesn't flap back down during a brief lull. **Trade-off:** CPU/memory HPA is simple but is a lagging proxy for "am I actually overloaded" for an I/O-bound app like this (most of the pod's time is spent waiting on the LLM API, not burning CPU). A queue-depth or request-latency-based scaler (KEDA, or a custom metrics adapter) would react faster and is the natural upgrade once real traffic data exists — not worth the extra moving part for a v1.
- **Redis — caching and rate limiting.** Identical-question answers are cached per-user for 5 minutes ([`app/cache.py`](app/cache.py)), so a spike of repeated questions (a common pattern for "how do I do X" DevOps queries) is served in <1ms and never touches the LLM API or its quota. Rate limiting is a Redis `INCR`+`EXPIRE` **fixed window** (20 req/min/user) — simple, O(1) per request, and enough to protect the LLM budget from a runaway client; the known trade-off vs. a sliding-window/token-bucket is it allows a short burst at the window boundary (up to ~2x the limit for a few seconds), which is acceptable here since the real backstop is the LLM Gateway's own concurrency/timeout handling, not the rate limiter alone.
- **Background queues.** Not deployed today — `/chat` is synchronous end-to-end (accept request → call LLM → return answer), which is fine up to a few hundred RPS if the LLM Gateway has enough concurrency headroom. Past that, or for any call the LLM Gateway is likely to run long (e.g. a larger/slower model, or a future RAG pipeline step), the plan is to put a queue (SQS, or RQ/Celery against the same Redis) between the API and the LLM Gateway: `/chat` enqueues, returns `202 Accepted` + a job id immediately, and the caller polls `/chat/{id}` or gets a webhook. This decouples request intake from LLM latency, so a slow LLM provider can't backpressure the whole API — pods stay free to accept new requests instead of blocking a worker on a stuck upstream call.
- **Rate limiting — protecting the app *and* the provider.** The same Redis limiter serves two purposes: protecting our own pods from a single noisy client, and protecting the Groq account's rate limit from being exhausted by our own traffic (a provider-side 429 for one user shouldn't be able to starve every other user).
- **LLM API limits (RPM / TPM / concurrency).** Groq enforces per-account requests-per-minute, tokens-per-minute, and concurrency caps. Today this is implicitly respected because our own per-user rate limit (20/min) times the pod count stays well under Groq's limits at this scale. At higher scale the LLM Gateway would own this explicitly: a global token-bucket per model shared across all pods (via Redis, since HPA means the limiter can't live in a single process), so the aggregate call rate to Groq is capped regardless of how many FastAPI pods are running — and the fallback model (`openai/gpt-oss-20b`) has separate headroom, so exhausting the primary model's quota doesn't exhaust the fallback's too.
- **Concurrent requests.** Each pod runs 2 Uvicorn workers ([`Dockerfile`](Dockerfile)); FastAPI's request handlers are sync `def` today, so each in-flight LLM call occupies one of Starlette's threadpool threads rather than blocking the event loop — multiple LLM calls per pod run concurrently. **Known limitation:** the SQLAlchemy calls in the same request path are also sync/blocking; at genuinely high concurrency, switching the DB driver to `asyncpg`/`async` SQLAlchemy would free up more headroom per pod before needing to scale out. Left as-is for now because Postgres calls here are short (single-row read/write), unlike the multi-second LLM call.
- **Failure recovery — retries, timeouts, fallback, graceful degradation.** `ask_llm()` ([`app/llm.py`](app/llm.py)) retries each model up to 3 times with exponential backoff (1–8s, via `tenacity`) and a 30s per-call timeout, then falls through to a second, smaller model if the primary is down or over quota. If *both* fail, `/chat` returns `503` with a clear message rather than a stack trace or a hang — the caller can retry instead of the request piling up. **Not yet implemented, and the next thing I'd add:** a circuit breaker in front of the LLM Gateway (e.g. `pybreaker`) so that once Groq is clearly down, pods fail fast instead of spending 3×backoff on every single request while the provider is unreachable — that's the difference between "degraded but responsive" and "every pod thread stuck waiting on a dead upstream."
- **PodDisruptionBudget.** `minAvailable: 1` ensures a node drain / rolling deploy never takes the app fully offline, working together with `maxUnavailable: 0` on the rolling update strategy for zero-downtime deploys.

## Migration: Single EC2 → Production (10 → 10,000 users)

**Scenario:** today's equivalent starting point is a Python LLM app on one EC2 instance, fine for ~10 users, that needs to serve 10,000 without the periodic slowness/crashes an external LLM API call on a single process causes.

**Target architecture** (this repo, deployed): `Users → Load Balancer → Kubernetes (EKS) → FastAPI Instances (HPA) → Redis / Queue → LLM Gateway → LLM APIs`, PostgreSQL for persistent state — i.e. everything above in *Scaling Scenario*, applied to a cold start instead of an existing fleet.

- **Scaling the application.** Containerize first (this repo already has a [`Dockerfile`](Dockerfile)) — that alone decouples "the app" from "the one EC2 box," and is the prerequisite for everything else. Then move from 1 process to N stateless pods behind a Kubernetes `Deployment` + HPA, exactly as in the *Scaling Scenario* section above. EKS over raw EC2 autoscaling groups because we get rolling updates, health-check-driven traffic shifting, and namespace-level isolation for free; ECS Fargate is the credible alternative if the team wants to avoid operating a control plane — the trade-off is less flexibility (no DaemonSets/sidecars like the Filebeat pattern used here) for less operational overhead.
- **Handling LLM API limits.** Same token-bucket-per-model approach as above, but now essential rather than optional: at 10,000 users, a single EC2 process serially awaiting the LLM API *is* the crash/slowness cause described in the scenario — one slow provider call blocks everything behind it. The fix is structural: the LLM Gateway becomes a distinct concern (still in-process initially, extractable into its own service later) that centrally tracks quota usage across all pods via Redis, so the fleet never collectively exceeds the provider's RPM/TPM even though no single pod knows about the others.
- **Slow/failing LLM requests.** Per-call timeout (30s, already implemented) so one slow upstream call can't hang a worker indefinitely; retry with exponential backoff for transient errors; fallback to a smaller/faster model when the primary is degraded; and — new for this scale — a circuit breaker that stops sending traffic to a provider that's clearly down, instead of every request paying the full retry cost against a dead endpoint.
- **Where Redis and queues go.** Redis stays in its current two jobs — answer cache (cuts repeat load on the LLM entirely) and distributed rate limiter (the *only* correct place for a rate limit once there's more than one app process, since in-memory counters on a single EC2 box don't survive going multi-instance). A queue (SQS or Redis-backed RQ/Celery) sits between the API and the LLM Gateway specifically to absorb the gap between "10 users, always-available capacity" and "10,000 users, bursty demand" — requests that would otherwise queue up inside a single process's threadpool instead queue durably, survive a pod restart, and let the API respond `202` immediately instead of holding a connection open for a slow LLM call.
- **Retries, timeouts, fallback.** Unchanged in mechanism from the *Scaling Scenario* section (`tenacity` retry + timeout + model fallback in [`app/llm.py`](app/llm.py)) — what changes at 10,000 users is that these need to be **provider-request-level**, not application-request-level: a retry storm from many pods hitting a struggling provider at once is worse than one EC2 box doing it, so backoff needs jitter and the circuit breaker becomes load-bearing rather than nice-to-have.
- **Monitoring.** Prometheus scrapes `/metrics` from every pod (request count/status, chat latency histogram, token usage, cache hits, rate-limit hits — all already exported in [`app/metrics.py`](app/metrics.py)) into Grafana dashboards; logs ship via a Filebeat sidecar into the ELK stack for searchable request/error logs. At 10,000-user scale, the two things worth adding beyond what's here: alerting on the leading indicators (rate-limit-hit rate climbing, cache-hit ratio dropping, p99 chat latency) rather than just the health check, and per-model token-usage dashboards to catch cost blowups before the monthly bill does.
- **Handling failures.** `PodDisruptionBudget` (min 1 available) + `RollingUpdate` with `maxUnavailable: 0` mean a node drain or deploy never drops capacity to zero; readiness probes pull an unhealthy pod out of the LB automatically; multi-AZ EKS node groups and an RDS Multi-AZ Postgres instance (vs. today's single-AZ container) cover infrastructure-level failure. None of this is possible on a single EC2 instance — that's the core reason a single box "occasionally becomes slow or crashes": there is no redundancy to fail over to.
- **Migrating with minimal downtime.** (1) Containerize and get the app running identically in a new EKS namespace, pointed at a **copy** of production data — no traffic yet. (2) Stand up RDS Postgres, seed it from an EC2 pg_dump/snapshot, and if the cutover window needs to be long, run logical replication from the EC2 Postgres to RDS so it stays current. (3) Point the app's `DATABASE_URL`/`REDIS_URL` at the new managed services and validate against a staging subdomain. (4) Cut over traffic gradually — weighted DNS or ALB target-group shifting (e.g. 5% → 25% → 100% to EKS) rather than an instant flip, watching error rate and latency at each step, with the EC2 box left running as an instant rollback target. (5) Only decommission EC2 after a burn-in period (e.g. 48–72h) with zero traffic and no incidents.
- **Managing secrets/configuration.** Move off "`.env` file on the EC2 box" entirely: Kubernetes `Secret` objects (as already done — `kubectl create secret generic infragpt-secrets`) backed by AWS Secrets Manager via the External Secrets Operator, so secrets are never stored in a manifest, image, or git history and can be rotated centrally without a redeploy. CI/CD (Jenkins here) injects credentials at pipeline runtime rather than baking them into the image, matching the "no hard-coded secrets" requirement end-to-end from laptop → CI → cluster.

## Secrets Management

All secrets are passed as environment variables — never hard-coded.
- Local: `.env` file or `export`
- Kubernetes: `kubectl create secret generic infragpt-secrets --from-literal=GROQ_API_KEY=...`
- Jenkins: stored as Jenkins credentials, injected at pipeline runtime
