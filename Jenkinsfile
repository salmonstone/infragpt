pipeline {
    agent any

    environment {
        DOCKERHUB_CREDS = credentials('dockerhub-creds')
        DOCKERHUB_REPO  = 'salmonstone/infragpt'
        IMAGE_TAG       = "${BUILD_NUMBER}"
        GROQ_API_KEY    = credentials('groq-api-key')
        K8S_NS          = 'infragpt'
    }

    stages {

        stage('📥 Checkout') {
            steps {
                echo '--- Pulling code from GitHub ---'
                git branch: 'main',
                    url: 'https://github.com/salmonstone/infragpt.git'
            }
        }

        stage('🐳 Docker Build') {
            steps {
                echo '--- Building Docker image ---'
                sh 'docker build -t ${DOCKERHUB_REPO}:${IMAGE_TAG} .'
                sh 'docker tag ${DOCKERHUB_REPO}:${IMAGE_TAG} ${DOCKERHUB_REPO}:latest'
                sh 'docker images | grep infragpt'
            }
        }

        stage('🔐 Trivy Security Scan') {
            steps {
                echo '--- Scanning image for vulnerabilities ---'
                sh '''
                    trivy image \
                        --exit-code 0 \
                        --severity HIGH,CRITICAL \
                        --format table \
                        ${DOCKERHUB_REPO}:${IMAGE_TAG}
                '''
            }
        }

        stage('📤 Push to DockerHub') {
            steps {
                echo '--- Pushing image to DockerHub ---'
                sh 'echo ${DOCKERHUB_CREDS_PSW} | docker login -u ${DOCKERHUB_CREDS_USR} --password-stdin'
                sh 'docker push ${DOCKERHUB_REPO}:${IMAGE_TAG}'
                sh 'docker push ${DOCKERHUB_REPO}:latest'
            }
        }

        stage('🏗️ Terraform Apply') {
            steps {
                echo '--- Provisioning AWS infrastructure ---'
                dir('terraform') {
                    sh 'terraform init'
                    sh 'terraform apply -auto-approve'
                }
            }
        }

        stage('☸️ Deploy to EKS') {
            steps {
                echo '--- Deploying to Kubernetes ---'
                sh 'aws eks update-kubeconfig --region ap-south-1 --name infragpt-cluster'
                sh 'kubectl create namespace ${K8S_NS} --dry-run=client -o yaml | kubectl apply -f -'
                sh '''kubectl create secret generic infragpt-secrets \
                        --from-literal=GROQ_API_KEY=${GROQ_API_KEY} \
                        --namespace=${K8S_NS} \
                        --dry-run=client -o yaml | kubectl apply -f -'''
                sh "sed -i 's|IMAGE_TAG_PLACEHOLDER|${IMAGE_TAG}|g' k8s/deployment.yaml"
                sh 'kubectl apply -f k8s/ --namespace=${K8S_NS}'
                sh 'kubectl rollout status deployment/infragpt --namespace=${K8S_NS} --timeout=180s'
            }
        }

        stage('✅ Health Check') {
            steps {
                echo '--- Checking app is live ---'
                sh '''
                    sleep 30
                    URL=$(kubectl get svc infragpt-service \
                        -n ${K8S_NS} \
                        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
                    echo "App URL: http://${URL}"
                    curl -f http://${URL}/health && echo '✅ HEALTH CHECK PASSED' || echo '⚠️ HEALTH CHECK FAILED'
                '''
            }
        }
    }

    post {
        success {
            echo '✅ PIPELINE SUCCEEDED! InfraGPT is LIVE!'
        }
        failure {
            echo '❌ PIPELINE FAILED - check stage logs above'
        }
        always {
            script {
                sh 'docker image prune -f || true'
                sh 'docker logout || true'
            }
        }
    }
}
