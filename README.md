# ⚡ InfraGPT — AI-Powered DevOps Assistant

An AI chatbot for DevOps and AWS questions, deployed on AWS EKS with a full **production-grade CI/CD pipeline**, **ELK stack logging**, **Helm packaging**, **Nginx Ingress**, and **zero-trust network policies**.

🌐 **Live:** [www.infragpt.online](http://www.infragpt.online) &nbsp;|&nbsp; 📊 **Kibana:** [kibana.infragpt.online](http://kibana.infragpt.online) &nbsp;|&nbsp; 👤 **Portfolio:** [your-portfolio-link]

`AWS` `Jenkins` `Docker` `Terraform` `Kubernetes` `Helm` `ELK Stack` `Groq` `Python`

---

## 🏗️ Architecture

```
                        ┌─────────────────────────┐
                        │   Developer Pushes Code  │
                        └────────────┬────────────┘
                                     │ GitHub Webhook
                                     ▼
                 ╔═══════════════════════════════════════╗
                 ║      Jenkins CI/CD  (12 Stages)       ║
                 ║                                       ║
                 ║  📥 Checkout  →  🐳 Docker Build      ║
                 ║  🔐 Trivy Scan →  📤 Push DockerHub   ║
                 ║  🏗️ Terraform  →  ☸️  kubectl Setup   ║
                 ║  🌐 Nginx Ingress → 📊 ELK Deploy     ║
                 ║  🔑 Secrets  →  🔒 Network Policies   ║
                 ║  ⎈  Helm Deploy  →  ✅ Health Check   ║
                 ╚══════════════════╦════════════════════╝
                                    ║
                                    ▼
          ╔═════════════════════════════════════════════════╗
          ║           AWS EKS Cluster  (ap-south-1)         ║
          ║                                                  ║
          ║   ┌──────────────────────────────────────────┐  ║
          ║   │          namespace: infragpt              │  ║
          ║   │                                          │  ║
          ║   │   ┌────────────────────────────────┐    │  ║
          ║   │   │     InfraGPT Pod  (2 → 6)      │    │  ║
          ║   │   │  ┌──────────┐  ┌────────────┐  │    │  ║
          ║   │   │  │ Flask App│  │  Filebeat  │  │    │  ║
          ║   │   │  │ Gunicorn │  │  Sidecar   │  │    │  ║
          ║   │   │  └────┬─────┘  └─────┬──────┘  │    │  ║
          ║   │   └───────┼──────────────┼──────────┘    │  ║
          ║   │     HPA ⟳ │    PDB 🛡️    │ logs          │  ║
          ║   └───────────┼──────────────┼───────────────┘  ║
          ║               │              │                   ║
          ║               ▼              ▼                   ║
          ║   ┌───────────────┐  ┌───────────────────────┐  ║
          ║   │  Nginx Ingress│  │  namespace: logging    │  ║
          ║   │  Controller   │  │                       │  ║
          ║   │  (Single ELB) │  │  Elasticsearch  📦    │  ║
          ║   └──────┬────────┘  │  Logstash       ⚙️    │  ║
          ║          │           │  Kibana         📊    │  ║
          ║          │           │  Filebeat DS    📡    │  ║
          ║          │           └───────────────────────┘  ║
          ╚══════════╬══════════════════════════════════════╝
                     ║
          ┌──────────╩────────────────────────┐
          │   www.infragpt.online  (App)       │
          │   kibana.infragpt.online (Logs)    │
          └────────────────────────────────────┘
                     │
                     ▼
              👤 User Browser
```

---

## 📊 ELK Logging — 4 Pipelines

```
┌─────────────────────────────────────────────────────────────┐
│                    Log Flow Architecture                     │
│                                                             │
│  Flask App  ──► Filebeat Sidecar  ──► Logstash :5044       │
│  K8s Pods   ──► Filebeat DaemonSet ──► Logstash :5045      │
│  Jenkins    ──► Logstash Plugin   ──► Logstash :5046       │
│  Nginx      ──► Filebeat DaemonSet ──► Logstash :5047      │
│                                           │                 │
│                                           ▼                 │
│                                    Elasticsearch            │
│                                           │                 │
│         infragpt-app-logs-*    ◄──────────┤                 │
│         infragpt-k8s-logs-*    ◄──────────┤                 │
│         infragpt-jenkins-logs-* ◄─────────┤                 │
│         infragpt-nginx-logs-*  ◄──────────┘                 │
│                                           │                 │
│                                           ▼                 │
│                                        Kibana               │
│                                  kibana.infragpt.online     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Engine | Groq API — llama-3.3-70b-versatile (free) |
| Backend | Python Flask + Gunicorn |
| Container | Docker multi-stage build |
| Registry | DockerHub |
| CI/CD | Jenkins (12-stage pipeline) |
| Security Scan | Trivy |
| IaC | Terraform (AWS VPC + EKS modules) |
| Packaging | Helm Chart |
| Orchestration | Kubernetes on AWS EKS |
| Ingress | Nginx Ingress Controller |
| Autoscaling | HPA — 2 to 6 pods, 60% CPU trigger |
| Logging | ELK Stack (Elasticsearch + Logstash + Kibana) |
| Log Shipping | Filebeat (DaemonSet + Sidecar) |
| Monitoring | Prometheus + Grafana |
| Security | Network Policies (zero-trust) + PodDisruptionBudget |
| TLS | cert-manager + Let's Encrypt (auto-renew) |
| Cloud | AWS — ap-south-1 Mumbai |

---

## 🚀 CI/CD Pipeline — 12 Stages

| # | Stage | What It Does |
|---|-------|-------------|
| 1 | 📥 Checkout | Pull latest code from GitHub |
| 2 | 🐳 Docker Build | Build multi-stage optimized image |
| 3 | 🔐 Trivy Scan | Scan for HIGH/CRITICAL vulnerabilities |
| 4 | 📤 Push | Push image to DockerHub with build tag |
| 5 | 🏗️ Terraform Apply | Provision VPC + EKS cluster on AWS |
| 6 | ☸️ Configure kubectl | Connect Jenkins to EKS cluster |
| 7 | 🌐 Nginx Ingress | Install/verify Nginx Ingress Controller |
| 8 | 📊 ELK Stack | Deploy Elasticsearch + Logstash + Kibana + Filebeat |
| 9 | 🔑 Namespace + Secrets | Create K8s namespace and inject API keys |
| 10 | 🔒 Network Policies | Apply zero-trust network rules |
| 11 | ⎈ Helm Deploy | Deploy app with Filebeat sidecar via Helm |
| 12 | ✅ Health Check | Verify app, HPA, PDB and sidecar status |

---

## ⚙️ Key Features

- **Zero downtime deploys** — RollingUpdate strategy, maxUnavailable: 0
- **Auto-scaling** — HPA scales pods 2→6 on 60% CPU or 70% memory
- **Node scaling** — EKS node group scales 1→3 t3.medium instances
- **PodDisruptionBudget** — always keeps minimum 1 pod alive during node drains
- **Single LoadBalancer** — Nginx Ingress routes all traffic via one AWS ELB
- **Helm packaging** — versioned, rollback-capable deployments
- **Centralised logging** — ELK stack with 4 separate date-indexed pipelines
- **Filebeat sidecar** — app logs shipped from inside the pod
- **Zero-trust networking** — 11 NetworkPolicy rules across namespaces
- **TLS** — cert-manager + Let's Encrypt, auto-renews every 90 days
- **Security** — Trivy scan every build, K8s secrets, non-root container
- **Full IaC** — entire AWS infrastructure defined in Terraform
- **Webhook trigger** — every git push auto-triggers full 12-stage pipeline
- **Free AI** — Groq API (llama-3.3-70b-versatile), no OpenAI costs

---

## 📁 Project Structure

```
infragpt/
├── app/
│   ├── main.py                    # Flask AI app — chat, health, metrics
│   ├── requirements.txt
│   └── templates/
│       └── index.html             # Dark terminal-style chat UI
│
├── elk/
│   ├── 01-elasticsearch.yaml      # StatefulSet + 20Gi EBS PVC
│   ├── 02-logstash.yaml           # 4 pipeline configs + Deployment
│   ├── 03-kibana.yaml             # Deployment + Ingress
│   └── 04-filebeat.yaml           # DaemonSet + Sidecar ConfigMap
│
├── helm/
│   └── infragpt/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── deployment.yaml    # App + Filebeat sidecar template
│           └── service-ingress-hpa-pdb.yaml
│
├── jenkins/
│   ├── Jenkinsfile                # 12-stage CI/CD pipeline
│   └── logstash-nodeport.yaml     # Expose Logstash to Jenkins EC2
│
├── k8s/
│   ├── deployment.yaml            # Deployment + Sidecar + PDB + HPA
│   ├── ingress.yaml               # Nginx Ingress + TLS
│   └── network-policies.yaml      # 11 zero-trust rules
│
├── monitoring/
│   └── prometheus-config.yaml
│
├── terraform/
│   ├── main.tf                    # VPC + EKS Terraform modules
│   └── variables.tf               # Region, CIDR, AZ config
│
└── Dockerfile                     # Multi-stage build (non-root user)
```

---

## 🔒 Network Policies — Zero Trust

```
Default Rule: DENY ALL ingress + egress for every namespace

Explicit Allows:
✅ Nginx Ingress  ──►  App           (port 5000)
✅ Prometheus     ──►  App scrape    (port 5000)
✅ App            ──►  Groq API      (HTTPS 443)
✅ App            ──►  Logstash      (port 5044)
✅ Filebeat DS    ──►  Logstash      (ports 5044-5047)
✅ Logstash       ──►  Elasticsearch (port 9200)
✅ Kibana         ──►  Elasticsearch (port 9200)
✅ Nginx Ingress  ──►  Kibana        (port 5601)
```

---

## 🔐 Security Highlights

- API keys stored as Jenkins credentials and Kubernetes secrets — never hardcoded
- Docker image runs as non-root user (appuser)
- Trivy scans every image before push — report archived in Jenkins
- IAM role attached to EC2 — no AWS access keys stored on disk
- K8s NetworkPolicies — zero-trust between all namespaces
- Resource limits — prevent container resource abuse
- TLS via cert-manager + Let's Encrypt (auto-renews every 90 days)

---

## 📊 Kubernetes Configuration

```
Replicas:       2 minimum → 6 maximum (HPA)
CPU trigger:    scale up at 60% utilization
Memory trigger: scale up at 70% utilization
Strategy:       RollingUpdate (maxUnavailable: 0)
Probes:         liveness + readiness on /health
PDB:            minAvailable: 1 (always 1 pod alive)
Resources:      requests 150m CPU / 256Mi RAM
                limits   600m CPU / 768Mi RAM
```

---

## ⎈ Helm — Quick Commands

```bash
# Deploy
helm upgrade --install infragpt ./helm/infragpt \
  --set image.tag=42 \
  --set filebeat.enabled=true \
  --namespace infragpt

# Status
helm status infragpt -n infragpt

# History
helm history infragpt -n infragpt

# Rollback
helm rollback infragpt 0 -n infragpt
```

---

## 🗣️ What InfraGPT Can Answer

- AWS (EC2, EKS, S3, IAM, VPC, Lambda, CloudWatch)
- Docker and container best practices
- Kubernetes (deployments, HPA, debugging, ELK)
- Terraform IaC patterns
- Jenkins CI/CD pipelines
- Helm charts and GitOps
- ELK Stack and observability
- Prometheus and Grafana monitoring
- Linux and Bash scripting
- Network security and zero-trust

---

## 👤 Author

**Aryan Singh Chauhan**

🐙 GitHub: [@salmonstone](https://github.com/salmonstone)
📧 Email: arysingh9832@gmail.com
🌐 Live Demo: [www.infragpt.online](http://www.infragpt.online)
📊 Kibana: [kibana.infragpt.online](http://kibana.infragpt.online)

---

⭐ If you found this useful, give it a star!

