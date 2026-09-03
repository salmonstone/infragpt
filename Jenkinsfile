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
          if ! command -v trivy > /dev/null 2>&1; then
            echo "Installing Trivy..."
            curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin
          fi
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
            sh 'terraform init'
            sh 'terraform apply -auto-approve'
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
        echo "Nginx Ingress already installed - skipping"
      else
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/aws/deploy.yaml

        sleep 30

        kubectl wait --namespace ingress-nginx \
          --for=condition=ready pod \
          --selector=app.kubernetes.io/component=controller \
          --timeout=180s
      fi
      kubectl get svc -n ingress-nginx

      # Install cert-manager for TLS (Let's Encrypt)
      if kubectl get ns cert-manager > /dev/null 2>&1; then
        echo "cert-manager already installed - skipping"
      else
        kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
        echo "Waiting for cert-manager to be ready..."
        kubectl wait --namespace cert-manager \
          --for=condition=ready pod \
          --selector=app.kubernetes.io/instance=cert-manager \
          --timeout=120s
      fi

      # Apply ClusterIssuer for Let's Encrypt
      kubectl apply -f k8s/cert-manager.yaml
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
      # Ensure infragpt namespace exists before applying filebeat (which has resources there)
      kubectl create namespace ${K8S_NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

      kubectl apply -f elk/01-elasticsearch.yaml

      # Wait for the Elasticsearch PVC to bind (EBS volume provisioning can take 2-4 min)
      echo "Waiting for Elasticsearch PVC to bind..."
      for i in $(seq 1 24); do
        PVC_STATUS=$(kubectl get pvc -n ${ELK_NAMESPACE} -l app=elasticsearch \
          -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
        echo "PVC status: ${PVC_STATUS} (attempt ${i}/24)"
        if [ "${PVC_STATUS}" = "Bound" ]; then
          echo "PVC bound successfully"
          break
        fi
        sleep 10
      done

      # Wait for Elasticsearch pod to be ready (handles EBS attach + JVM startup)
      echo "Waiting for Elasticsearch to be ready..."
      kubectl rollout status statefulset/elasticsearch \
        -n ${ELK_NAMESPACE} --timeout=300s

      kubectl apply -f elk/02-logstash.yaml
      kubectl apply -f elk/03-kibana.yaml
      kubectl apply -f elk/04-filebeat.yaml

      # Wait for Logstash to be ready before Helm deploys the app with filebeat sidecar
      echo "Waiting for Logstash to be ready..."
      kubectl rollout status deployment/logstash \
        -n ${ELK_NAMESPACE} --timeout=180s

      echo "ELK Stack deployed successfully"
      kubectl get pods -n ${ELK_NAMESPACE}
    '''
  }
}
 
 
    stage('Apply Network Policies') {
      steps {
        sh '''
          echo "Network policies skipped"
          kubectl get networkpolicies -n ${K8S_NAMESPACE}
          kubectl get networkpolicies -n ${ELK_NAMESPACE}
        '''
      }
    }
 
    stage('Helm Deploy') {
  steps {
    sh '''
      helm version

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
      echo 'PIPELINE SUCCEEDED - InfraGPT Phase 2 is live!'
    }
    failure {
      echo 'PIPELINE FAILED - rolling back Helm release...'
      sh 'helm rollback ${HELM_RELEASE} 0 -n ${K8S_NAMESPACE} || true'
    }
  }
}
