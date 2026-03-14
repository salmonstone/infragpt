# ⚡ InfraGPT — AI-Powered DevOps Assistant

> An AI chatbot for DevOps and AWS questions, deployed on AWS EKS with a full production-grade CI/CD pipeline.

![AWS](https://img.shields.io/badge/AWS-EKS-orange?logo=amazon-aws)
![Jenkins](https://img.shields.io/badge/CI%2FCD-Jenkins-red?logo=jenkins)
![Docker](https://img.shields.io/badge/Container-Docker-blue?logo=docker)
![Terraform](https://img.shields.io/badge/IaC-Terraform-purple?logo=terraform)
![Kubernetes](https://img.shields.io/badge/Orchestration-Kubernetes-326CE5?logo=kubernetes)
![Groq](https://img.shields.io/badge/AI-Groq%20LLM-green)
![Python](https://img.shields.io/badge/Backend-Python%20Flask-yellow?logo=python)

---

## 🏗️ Architecture
```
Developer (git push)
        ↓ GitHub webhook triggers
┌─────────────────────────────────────────┐
│         Jenkins CI/CD Pipeline          │
│  Checkout → Docker Build → Trivy Scan  │
│  → Push DockerHub → Terraform Apply    │
│  → Deploy EKS → Health Check          │
└─────────────────────┬───────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│     AWS EKS Cluster — ap-south-1       │
│  VPC + Public/Private Subnets          │
│  NAT Gateway + Internet Gateway        │
│  Kubernetes Deployment (2→6 pods)      │
│  HPA Autoscaling + Rolling Updates     │
│  Prometheus + Grafana Monitoring       │
└─────────────────────┬───────────────────┘
                      ↓
         LoadBalancer → Public URL
                      ↓
            User Browser — Chat UI
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| AI Engine | Groq API — llama-3.3-70b-versatile (free) |
| Backend | Python Flask + Gunicorn |
| Container | Docker multi-stage build |
| Registry | DockerHub |
| CI/CD | Jenkins (7-stage pipeline) |
| Security Scan | Trivy |
| IaC | Terraform (AWS VPC + EKS modules) |
| Orchestration | Kubernetes on AWS EKS |
| Autoscaling | HPA — 2 to 6 pods, 60% CPU trigger |
| Monitoring | Prometheus + Grafana |
| Cloud | AWS — ap-south-1 Mumbai |

---

## 🚀 CI/CD Pipeline Stages

| Stage | What It Does |
|---|---|
| 📥 Checkout | Pull latest code from GitHub |
| 🐳 Docker Build | Build multi-stage optimized image |
| 🔐 Trivy Scan | Scan for HIGH/CRITICAL vulnerabilities |
| 📤 Push | Push image to DockerHub with build tag |
| 🏗️ Terraform Apply | Provision VPC + EKS cluster on AWS |
| ☸️ Deploy to EKS | kubectl apply to infragpt namespace |
| ✅ Health Check | Verify /health endpoint is live |

---

## ⚙️ Key Features

- **Zero downtime deploys** — RollingUpdate strategy, `maxUnavailable: 0`
- **Auto-scaling** — HPA scales pods 2→6 on 60% CPU or 70% memory
- **Node scaling** — EKS node group scales 1→3 t3.medium instances
- **Security** — Trivy scan every build, K8s secrets, non-root container user
- **Full IaC** — entire AWS infrastructure defined in Terraform, nothing manual
- **Webhook trigger** — every `git push` to main auto-triggers full pipeline
- **Monitoring** — Prometheus scrapes `/metrics` every 15s, Grafana dashboards
- **Free AI** — Groq API (llama-3.3-70b-versatile), no OpenAI costs

---

## 📁 Project Structure
```
infragpt/
├── app/
│   ├── main.py                 # Flask AI app — chat, health, metrics endpoints
│   ├── requirements.txt        # Python dependencies
│   └── templates/
│       └── index.html          # Dark terminal-style chat UI
├── Dockerfile                  # Multi-stage Docker build (non-root user)
├── Jenkinsfile                 # Full 7-stage CI/CD pipeline
├── terraform/
│   ├── main.tf                 # VPC + EKS Terraform modules
│   └── variables.tf            # Region, CIDR, AZ configuration
└── k8s/
    └── deployment.yaml         # Deployment + Service + HPA
```

---

## 🔐 Security Highlights

- API keys stored as Jenkins credentials and Kubernetes secrets — never hardcoded
- Docker image runs as non-root user (`appuser`)
- Trivy scans every image before push
- IAM role attached to EC2 — no AWS access keys stored on disk
- K8s resource limits prevent container resource abuse

---

## 📊 Kubernetes Configuration
```yaml
Replicas:      2 minimum → 6 maximum (HPA)
CPU trigger:   scale up at 60% utilization
Memory trigger: scale up at 70% utilization
Strategy:      RollingUpdate (maxUnavailable: 0)
Probes:        liveness + readiness on /health
Resources:     requests 100m CPU / 128Mi RAM
               limits   500m CPU / 512Mi RAM
```

---

## 🗣️ What InfraGPT Can Answer

- AWS (EC2, EKS, S3, IAM, VPC, Lambda, CloudWatch)
- Docker and container best practices
- Kubernetes (deployments, HPA, debugging)
- Terraform IaC patterns
- Jenkins CI/CD pipelines
- Prometheus and Grafana monitoring
- Linux and Bash scripting

---

## 👤 Author

**Aryan Singh Chauhan**
- 🐙 GitHub: [@AryanSingh9832](https://github.com/AryanSingh9832)
- 📧 Email: arysingh9832@gmail.com


---

## ⭐ If you found this useful, give it a star!
