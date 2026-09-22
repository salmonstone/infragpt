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

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | No | Get JWT token |
| POST | `/chat` | JWT | Ask a DevOps question |
| GET | `/health` | No | Health check |
| GET | `/metrics` | No | Prometheus metrics |
| GET | `/history` | JWT | Chat history |
| GET | `/` | No | Web UI |

## Roles (RBAC)

| Role | `/chat` | `/history` | `/metrics` |
|---|---|---|---|
| `admin` | ✅ All users' history | ✅ | ✅ |
| `user` | ✅ Own history only | ✅ | ✅ |
| `readonly` | ❌ Blocked | ✅ | ✅ |

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

Default users seeded on first start:
- `admin` / `admin123` (role: admin)
- `user1` / `user123` (role: user)

## Run Tests

```bash
cd tests
pip install pytest httpx fastapi
pytest test_api.py -v
```

## Production Deployment (AWS EKS)

Jenkins pipeline handles:
1. Docker build + Trivy scan → DockerHub
2. Terraform — EKS cluster, VPC, EBS CSI driver
3. Helm deploy — app + HPA + PDB + Ingress + TLS (Let's Encrypt)
4. ELK Stack — Elasticsearch, Logstash, Kibana, Filebeat sidecar

```bash
# Manual Helm deploy
helm upgrade --install infragpt ./helm/infragpt \
  --namespace infragpt \
  --set image.tag=<BUILD_NUMBER>
```

## Scaling Design

- **HPA**: 2 → 6 pods at 60% CPU / 70% memory
- **Redis cache**: identical questions served in <1ms (5min TTL)
- **Rate limiting**: 20 req/min per user via Redis sliding window
- **LLM retry**: 3 attempts with exponential backoff, fallback to `llama3-8b-8192`
- **PodDisruptionBudget**: min 1 pod always available during node drain

## Secrets Management

All secrets are passed as environment variables — never hard-coded.
- Local: `.env` file or `export`
- Kubernetes: `kubectl create secret generic infragpt-secrets --from-literal=GROQ_API_KEY=...`
- Jenkins: stored as Jenkins credentials, injected at pipeline runtime
