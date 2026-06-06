pipeline {
  agent any

  environment {
    DOCKERHUB_CREDENTIALS = credentials('dockerhub-creds')
    DOCKERHUB_REPO        = 'salmonstone/infragpt'
    IMAGE_TAG             = "${BUILD_NUMBER}"
    GROQ_API_KEY          = credentials('groq-api-key')
    K8S_NAMESPACE         = 'infragpt'
    AWS_REGION            = 'ap-south-1'
    CLUSTER_NAME          = 'infragpt-cluster'
    HELM_RELEASE          = 'infragpt'
    INGRESS_NAMESPACE     = 'ingress-nginx'
    ELK_NAMESPACE         = 'logging'
    PATH                  = "/usr/local/bin:${env.PATH}"
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '10'))
    timeout(time: 45, unit: 'MINUTES')
    disableConcurrentBuilds()
  }

  stages {

    stage('Checkout') {
      steps {
        git branch: 'main',
            url: 'https://github.com/salmonstone/infragpt.git'
        echo "Checked out: ${GIT_COMMIT}"
      }
    }

    stage('Install Tools') {
      steps {
        sh '''
          # Install Helm if not present
          if ! command -v helm > /dev/null 2>&1; then
            echo "Installing Helm..."
            curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
          else
            echo "Helm already installed: $(helm version --short)"
          fi

          # Install kubectl if not present
          if ! command -v kubectl > /dev/null 2>&1; then
            echo "Installing kubectl..."
            curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
            sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
          else
            echo "kubectl already installed: $(kubectl version --client --short)"
          fi

          # Install Trivy if not present
          if ! command -v trivy > /dev/null 2>&1; then
            echo "Installing Trivy..."
            sudo rpm -ivh https://github.com/aquasecurity/trivy/releases/download/v0.50.1/trivy_0.50.1_Linux-64bit.rpm || true
          else
            echo "Trivy already installed: $(trivy --version)"
          fi

          # Install Terraform if not present
          if ! command -v terraform > /dev/null 2>&1; then
            echo "Installing Terraform..."
            sudo yum install -y yum-utils || true
            sudo yum-config-manager --add-repo https://rpm.releases.hashicorp.com/AmazonLinux/hashicorp.repo || true
            sudo yum install -y terraform || true
          else
            echo "Terraform already installed: $(terraform version -json | head -1)"
          fi

          echo "=== Tool Versions ==="
          helm version --short
          kubectl version --client --short
          docker --version
          aws --version
        '''
      }
    }

    stage('Docker Build') {
      steps {
        sh '''
          docker build \
            -t ${DOCKERHUB_REPO}:${IMAGE_TAG} \
            -t ${DOCKERHUB_REPO}:latest .
        '''
      }
    }

    stage('Trivy Security Scan') {
      steps {
        sh '''
          trivy image \
            --exit-code 0 \
            --severity HIGH,CRITICAL \
            --format table \
            --output trivy-report-${IMAGE_TAG}.txt \
            ${DOCKERHUB_REPO}:${IMAGE_TAG}
          cat trivy-report-${IMAGE_TAG}.txt
        '''
        archiveArtifacts artifacts: "trivy-report-${IMAGE_TAG}.txt",
                         allowEmptyArchive: true
      }
    }

    stage('Push to DockerHub') {
      steps {
        sh '''
          echo ${DOCKERHUB_CREDENTIALS_PSW} | \
            docker login -u ${DOCKERHUB_CREDENTIALS_USR} --password-stdin
          docker push ${DOCKERHUB_REPO}:${IMAGE_TAG}
          docker push ${DOCKERHUB_REPO}:latest
        '''
      }
    }

    stage('Terraform Provision') {
      steps {
        dir('terraform') {
          sh '''
            terraform init
            terraform apply -auto-approve
          '''
        }
      }
    }

    stage('Configure kubectl') {
      steps {
        sh '''
          aws eks update-kubeconfig \
            --region ${AWS_REGION} \
            --name ${CLUSTER_NAME}
          kubectl get nodes
        '''
      }
    }

    stage('Nginx Ingress Controller') {
      steps {
        sh '''
          if kubectl get ns ingress-nginx > /dev/null 2>&1; then
            echo "Nginx Ingress already installed — skipping"
          else
            kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/aws/deploy.yaml
            sleep 30
            kubectl wait --namespace ingress-nginx \
              --for=condition=ready pod \
              --selector=app.kubernetes.io/component=controller \
              --timeout=180s
          fi
          kubectl get svc -n ingress-nginx
        '''
      }
    }

    stage('Namespace + Secrets') {
      steps {
        sh '''
          kubectl create namespace ${K8S_NAMESPACE} \
            --dry-run=client -o yaml | kubectl apply -f -

          kubectl create secret generic infragpt-secrets \
            --from-literal=GROQ_API_KEY=${GROQ_API_KEY} \
            --namespace=${K8S_NAMESPACE} \
            --dry-run=client -o yaml | kubectl apply -f -
        '''
      }
    }

    stage('ELK Stack Deploy') {
      steps {
        sh '''
          kubectl apply -f elk/01-elasticsearch.yaml
          kubectl apply -f elk/02-logstash.yaml
          kubectl apply -f elk/03-kibana.yaml
          kubectl apply -f elk/04-filebeat.yaml
          echo "ELK Stack applied — Elasticsearch starting in background"
          sleep 30
          kubectl get pods -n ${ELK_NAMESPACE}
        '''
      }
    }

    stage('Apply Network Policies') {
      steps {
        sh '''
          echo "Network policies skipped"
          kubectl get networkpolicies -n ${K8S_NAMESPACE} || true
          kubectl get networkpolicies -n ${ELK_NAMESPACE} || true
        '''
      }
    }

    stage('Helm Deploy') {
      steps {
        sh '''
          helm upgrade --install ${HELM_RELEASE} ./helm/infragpt \
            --namespace ${K8S_NAMESPACE} \
            --set image.repository=${DOCKERHUB_REPO} \
            --set image.tag=${IMAGE_TAG} \
            --set filebeat.enabled=true \
            --set networkPolicy.enabled=true \
            --set ingress.enabled=true \
            --atomic \
            --timeout 5m \
            --wait

          helm status ${HELM_RELEASE} -n ${K8S_NAMESPACE}
        '''
      }
    }

    stage('Health Check') {
      steps {
        sh '''
          kubectl rollout status deployment/${HELM_RELEASE} \
            -n ${K8S_NAMESPACE} --timeout=120s

          sleep 30
          INGRESS_URL=$(kubectl get ingress infragpt-ingress \
            -n ${K8S_NAMESPACE} \
            -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

          echo "Ingress URL: ${INGRESS_URL}"

          if [ -n "${INGRESS_URL}" ]; then
            HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
              http://${INGRESS_URL}/health || echo "000")
            echo "Health check status: ${HTTP_STATUS}"
          fi

          echo "--- Pod Status ---"
          kubectl get pods -n ${K8S_NAMESPACE}
          echo "--- HPA Status ---"
          kubectl get hpa -n ${K8S_NAMESPACE}
          echo "--- PDB Status ---"
          kubectl get pdb -n ${K8S_NAMESPACE}
          echo "--- Filebeat Sidecar Logs ---"
          kubectl logs -l app=infragpt -c filebeat-sidecar \
            -n ${K8S_NAMESPACE} --tail=20 || true
        '''
      }
    }
  }

  post {
    always {
      sh 'docker image prune -f || true'
      sh 'docker logout || true'
    }
    success {
      echo 'PIPELINE SUCCEEDED — InfraGPT is live!'
    }
    failure {
      echo 'PIPELINE FAILED — rolling back Helm release...'
      sh 'helm rollback ${HELM_RELEASE} 0 -n ${K8S_NAMESPACE} || true'
    }
  }
}
