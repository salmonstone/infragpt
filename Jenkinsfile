pipeline {
  agent any
 
  environment {
    DOCKERHUB_CREDENTIALS = credentials('dockerhub-creds')
    DOCKERHUB_REPO        = '/infragpt'
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
            terraform init -input=false
            terraform plan -out=tfplan -input=false
            terraform apply -input=false tfplan
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
          if kubectl get ns ${INGRESS_NAMESPACE} > /dev/null 2>&1; then
            echo "Nginx Ingress already installed — skipping"
          else
            kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/aws/deploy.yaml
            kubectl wait --namespace ${INGRESS_NAMESPACE} \
              --for=condition=ready pod \
              --selector=app.kubernetes.io/component=controller \
              --timeout=180s
            echo "Nginx Ingress Controller ready"
          fi
          kubectl get svc -n ${INGRESS_NAMESPACE}
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
 
          kubectl rollout status statefulset/elasticsearch \
            -n ${ELK_NAMESPACE} --timeout=300s
 
          kubectl rollout status deployment/logstash \
            -n ${ELK_NAMESPACE} --timeout=180s
 
          kubectl get pods -n ${ELK_NAMESPACE}
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
 
    stage('Apply Network Policies') {
      steps {
        sh '''
          kubectl apply -f k8s/network-policies.yaml
          kubectl get networkpolicies -n ${K8S_NAMESPACE}
          kubectl get networkpolicies -n ${ELK_NAMESPACE}
        '''
      }
    }
 
    stage('Helm Deploy') {
      steps {
        sh '''
          if ! command -v helm &> /dev/null; then
            curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
          fi
 
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
      echo 'PIPELINE SUCCEEDED — InfraGPT Phase 2 is live!'
    }
    failure {
      echo 'PIPELINE FAILED — rolling back Helm release...'
      sh 'helm rollback ${HELM_RELEASE} 0 -n ${K8S_NAMESPACE} || true'
    }
  }
}
