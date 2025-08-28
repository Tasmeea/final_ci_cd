pipeline {
    agent { label 'worker' }
    
    environment {
        DOCKER_REGISTRY = 'localhost:5000'
        APP_NAME = 'sensor-ml-system'
        SHARED_DATA_PATH = '/opt/sarawak-energy/shared-data'
        MODELS_PATH = '/opt/sarawak-energy/models'
        JENKINS_MASTER_URL = 'http://18.143.157.100:8080'
        ROBOT_SYSTEM_URL = 'http://18.143.157.100:5003'
    }
    
    triggers {
        pollSCM('*/60 * * * * *')
    }
    
    stages {
        stage('Setup ML Environment') {
            steps {
                script {
                    echo "Setting up ML environment on ${env.NODE_NAME}"
                    
                    sh """
                        mkdir -p ${SHARED_DATA_PATH}/{ml-data,models,temp}
                        mkdir -p ${MODELS_PATH}/{backup,staging,production}
                        chmod -R 755 ${SHARED_DATA_PATH} ${MODELS_PATH}
                    """
                    
                    sh """
                        python3 --version
                        pip3 list | grep -E 'scikit-learn|pandas|numpy' || echo 'ML packages check'
                    """
                }
            }
        }
        
        stage('Check for ML Triggers') {
            steps {
                script {
                    def triggerFiles = sh(
                        script: """
                            find ${SHARED_DATA_PATH} -name 'trigger_sensor-ml-pipeline_*' -newer /tmp/last_ml_check_${env.NODE_NAME} 2>/dev/null || echo 'none'
                        """,
                        returnStdout: true
                    ).trim()
                    
                    if (triggerFiles != 'none' && triggerFiles != '') {
                        echo "ML pipeline triggers detected on ${env.NODE_NAME}: ${triggerFiles}"
                        env.ML_TRIGGERED = 'true'
                        sh "touch /tmp/last_ml_check_${env.NODE_NAME}"
                    } else {
                        echo "No ML triggers found on ${env.NODE_NAME}"
                        env.ML_TRIGGERED = 'false'
                    }
                }
            }
        }
        
        stage('Deploy ML System') {
            when {
                environment name: 'ML_TRIGGERED', value: 'true'
            }
            steps {
                script {
                    echo "Deploying ML system on ${env.NODE_NAME}..."
                    
                    def isRunning = sh(
                        script: "docker ps | grep sarawak-sensor-ml-pipeline || echo 'not_running'",
                        returnStdout: true
                    ).trim()
                    
                    if (isRunning.contains('not_running')) {
                        echo "Starting ML system..."
                        
                        sh """
                            docker run -d \\
                                --name sarawak-sensor-ml-pipeline \\
                                --network sarawak-network \\
                                -p 5002:5000 \\
                                -v ${SHARED_DATA_PATH}:/app/shared-data \\
                                -v ${MODELS_PATH}:/app/models \\
                                -e ROBOT_SYSTEM_URL=${ROBOT_SYSTEM_URL} \\
                                --memory=2g \\
                                --cpus=2 \\
                                --restart unless-stopped \\
                                sarawak-sensor-ml:latest || echo 'ML container start failed'
                        """
                        
                        sleep(30)
                    }
                }
            }
        }
        
        stage('Analyze Sensor Data') {
            when {
                environment name: 'ML_TRIGGERED', value: 'true'
            }
            steps {
                script {
                    echo "Analyzing sensor data on ${env.NODE_NAME}..."
                    
                    def sensorDataSize = sh(
                        script: "find ${SHARED_DATA_PATH} -name 'sensor_data_*.json' -exec wc -c {} + | tail -1 | awk '{print \$1}' || echo '0'",
                        returnStdout: true
                    ).trim()
                    
                    echo "Total sensor data size: ${sensorDataSize} bytes"
                    
                    if (sensorDataSize.toInteger() > 1000) {
                        echo "Sufficient data available for ML training"
                        env.HAS_DATA = 'true'
                        
                        sh """
                            echo "Data analysis started at \$(date) on ${env.NODE_NAME}" > ${SHARED_DATA_PATH}/ml_analysis_${BUILD_NUMBER}.log
                            echo "Data size: ${sensorDataSize} bytes" >> ${SHARED_DATA_PATH}/ml_analysis_${BUILD_NUMBER}.log
                        """
                    } else {
                        echo "Insufficient data for ML training"
                        env.HAS_DATA = 'false'
                    }
                }
            }
        }
        
        stage('Train ML Model') {
            when {
                allOf {
                    environment name: 'ML_TRIGGERED', value: 'true'
                    environment name: 'HAS_DATA', value: 'true'
                }
            }
            steps {
                echo "Training ML model on ${env.NODE_NAME}..."
                
                script {
                    def response = sh(
                        script: """
                            timeout 300 curl -s -X POST http://localhost:5002/train_model \\
                            -H 'Content-Type: application/json' \\
                            -w '%{http_code}' || echo '500'
                        """,
                        returnStdout: true
                    ).trim()
                    
                    echo "Training response: ${response}"
                    
                    if (response.contains('200')) {
                        echo "Model training completed successfully on ${env.NODE_NAME}"
                        env.TRAINING_SUCCESS = 'true'
                        
                        sh """
                            echo "Training completed at \$(date) on ${env.NODE_NAME}" >> ${SHARED_DATA_PATH}/ml_training_${BUILD_NUMBER}.log
                        """
                    } else {
                        echo "Model training failed on ${env.NODE_NAME}"
                        env.TRAINING_SUCCESS = 'false'
                    }
                }
            }
        }
        
        stage('Validate and Deploy Model') {
            when {
                environment name: 'TRAINING_SUCCESS', value: 'true'
            }
            steps {
                script {
                    echo "Validating and deploying model on ${env.NODE_NAME}..."
                    
                    sleep(10)
                    
                    def modelInfo = sh(
                        script: "curl -s http://localhost:5002/model_info || echo '{\"error\": \"failed\"}'",
                        returnStdout: true
                    ).trim()
                    
                    echo "Model validation info: ${modelInfo}"
                    
                    if (!modelInfo.contains('error')) {
                        echo "Model validation successful on ${env.NODE_NAME}"
                        env.MODEL_VALID = 'true'
                        
                        sh """
                            mkdir -p ${MODELS_PATH}/backup/\$(date +%Y%m%d_%H%M%S)
                            cp ${MODELS_PATH}/*.joblib ${MODELS_PATH}/backup/\$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || echo 'No previous models'
                        """
                        
                        echo "Model deployed successfully on ${env.NODE_NAME}"
                    } else {
                        echo "Model validation failed on ${env.NODE_NAME}"
                        env.MODEL_VALID = 'false'
                    }
                }
            }
        }
        
        stage('Notify Robot Systems') {
            when {
                environment name: 'MODEL_VALID', value: 'true'
            }
            steps {
                script {
                    echo "Notifying robot systems from ${env.NODE_NAME}..."
                    
                    sh """
                        curl -s -X POST ${ROBOT_SYSTEM_URL}/threshold_alert \\
                        -H 'Content-Type: application/json' \\
                        -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["ML Model Updated"], "sensor_id": "ML_PIPELINE_${env.NODE_NAME}", "all_parameters": {"action": "model_update", "node": "${env.NODE_NAME}"}}' || echo 'Robot notification failed'
                    """
                    
                    echo "Robot systems notified of model update"
                }
            }
        }
    }
    
    post {
        always {
            echo "ML pipeline completed on ${env.NODE_NAME}"
            
            sh """
                mkdir -p ${SHARED_DATA_PATH}/logs/ml-pipeline
                mv ${SHARED_DATA_PATH}/ml_*_${BUILD_NUMBER}.log ${SHARED_DATA_PATH}/logs/ml-pipeline/ 2>/dev/null || echo 'No logs to archive'
                
                find ${SHARED_DATA_PATH} -name 'trigger_sensor-ml-pipeline_*' -mmin +120 -delete 2>/dev/null || echo 'No old triggers'
            """
        }
        
        success {
            echo "ML pipeline succeeded on ${env.NODE_NAME}"
        }
        
        failure {
            echo "ML pipeline failed on ${env.NODE_NAME}"
            
            sh """
                curl -s -X POST ${ROBOT_SYSTEM_URL}/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["ML Pipeline Failure"], "sensor_id": "JENKINS_ML_${env.NODE_NAME}"}' || echo 'Failure alert failed'
            """
        }
    }
}