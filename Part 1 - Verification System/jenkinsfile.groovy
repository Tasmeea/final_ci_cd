pipeline {
    agent { label 'worker-node-ec2' }
    
    environment {
        DOCKER_REGISTRY = 'localhost:5000'
        APP_NAME = 'verification-system'
        SHARED_DATA_PATH = '/opt/sarawak-energy/shared-data'
        JENKINS_MASTER_URL = 'http://18.143.157.100:8080'
        DB_HOST = '18.143.157.100'
        ROBOT_SYSTEM_URL = 'http://18.143.157.100:5003'
    }
    
    triggers {
        pollSCM('*/30 * * * * *')
    }
    
    stages {
        stage('Setup Environment') {
            steps {
                script {
                    echo "Setting up environment on ${env.NODE_NAME}"
                    
                    sh """
                        mkdir -p ${SHARED_DATA_PATH}/{archive,temp,logs}
                        chmod -R 755 ${SHARED_DATA_PATH}
                    """
                    
                    sh "docker --version"
                    sh "docker network ls | grep sarawak-network || docker network create sarawak-network"
                }
            }
        }
        
        stage('Check for New Visitors') {
            steps {
                script {
                    def visitorFiles = sh(
                        script: """
                            find ${SHARED_DATA_PATH} -name 'visitor_*.json' -newer /tmp/last_visitor_check_${env.NODE_NAME} 2>/dev/null || echo 'none'
                        """,
                        returnStdout: true
                    ).trim()
                    
                    if (visitorFiles != 'none' && visitorFiles != '') {
                        echo "New visitor files detected on ${env.NODE_NAME}: ${visitorFiles}"
                        env.NEW_VISITORS = 'true'
                        sh "touch /tmp/last_visitor_check_${env.NODE_NAME}"
                    } else {
                        echo "No new visitor files found on ${env.NODE_NAME}"
                        env.NEW_VISITORS = 'false'
                    }
                }
            }
        }
        
        stage('Deploy Verification System') {
            when {
                environment name: 'NEW_VISITORS', value: 'true'
            }
            steps {
                script {
                    echo "Deploying verification system on ${env.NODE_NAME}..."
                    
                    def isRunning = sh(
                        script: "docker ps | grep sarawak-verification-kiosk || echo 'not_running'",
                        returnStdout: true
                    ).trim()
                    
                    if (isRunning.contains('not_running')) {
                        echo "Starting verification system..."
                        
                        sh """
                            cd /opt/sarawak-energy
                            docker run -d \\
                                --name sarawak-verification-kiosk \\
                                --network sarawak-network \\
                                -p 5001:5000 \\
                                -v ${SHARED_DATA_PATH}:/app/shared-data \\
                                -e DATABASE_URL=postgresql://postgres:sarawak2024!@${DB_HOST}:5432/visitors \\
                                -e ROBOT_SYSTEM_URL=${ROBOT_SYSTEM_URL} \\
                                --restart unless-stopped \\
                                sarawak-verification:latest || echo 'Container start failed'
                        """
                    } else {
                        echo "Verification system already running"
                    }
                }
            }
        }
        
        stage('Process Visitor Data') {
            when {
                environment name: 'NEW_VISITORS', value: 'true'
            }
            steps {
                script {
                    echo "Processing visitor data on ${env.NODE_NAME}..."
                    
                    def visitorFiles = sh(
                        script: "find ${SHARED_DATA_PATH} -name 'visitor_*.json' -type f | head -10",
                        returnStdout: true
                    ).trim().split('\n')
                    
                    for (file in visitorFiles) {
                        if (file.trim()) {
                            echo "Processing visitor file: ${file}"
                            
                            try {
                                def visitorData = readJSON file: file
                                echo "Visitor: ${visitorData.name} -> Floor ${visitorData.destination_floor}"
                                
                                def response = sh(
                                    script: """
                                        curl -s -X POST ${ROBOT_SYSTEM_URL}/new_visitor \\
                                        -H 'Content-Type: application/json' \\
                                        -d @${file} \\
                                        -w '%{http_code}' || echo '500'
                                    """,
                                    returnStdout: true
                                ).trim()
                                
                                if (response.contains('200')) {
                                    echo "Successfully notified robot system"
                                    env.NOTIFICATION_SUCCESS = 'true'
                                } else {
                                    echo "Robot notification failed: ${response}"
                                    env.NOTIFICATION_SUCCESS = 'false'
                                }
                                
                            } catch (Exception e) {
                                echo "Error processing visitor file ${file}: ${e.getMessage()}"
                            }
                        }
                    }
                }
            }
        }
        
        stage('Archive Visitor Data') {
            when {
                environment name: 'NEW_VISITORS', value: 'true'
            }
            steps {
                script {
                    def today = new Date().format('yyyy-MM-dd')
                    def archiveDir = "${SHARED_DATA_PATH}/archive/${today}"
                    
                    sh """
                        mkdir -p ${archiveDir}
                        mv ${SHARED_DATA_PATH}/visitor_*.json ${archiveDir}/ 2>/dev/null || echo 'No files to archive'
                        echo "Processed at \$(date) on ${env.NODE_NAME}" >> ${archiveDir}/processing_log.txt
                    """
                    
                    echo "Visitor data archived to ${archiveDir} on ${env.NODE_NAME}"
                }
            }
        }
        
        stage('Health Check') {
            steps {
                script {
                    echo "Performing health check on ${env.NODE_NAME}..."
                    
                    def health = sh(
                        script: "curl -s http://localhost:5001/health || echo 'failed'",
                        returnStdout: true
                    ).trim()
                    
                    if (health.contains('healthy')) {
                        echo "Verification system is healthy"
                        env.SYSTEM_HEALTHY = 'true'
                    } else {
                        echo "Verification system health check failed"
                        env.SYSTEM_HEALTHY = 'false'
                    }
                    
                    def dbCheck = sh(
                        script: """
                            docker run --rm --network sarawak-network postgres:13 \\
                            psql postgresql://postgres:sarawak2024!@${DB_HOST}:5432/visitors \\
                            -c 'SELECT COUNT(*) FROM visitors;' || echo 'db_failed'
                        """,
                        returnStdout: true
                    ).trim()
                    
                    if (!dbCheck.contains('db_failed')) {
                        echo "Database connectivity confirmed"
                    } else {
                        echo "Database connectivity failed"
                    }
                }
            }
        }
    }
    
    post {
        always {
            echo "Verification pipeline completed on ${env.NODE_NAME}"
            
            sh """
                echo "Pipeline completed at \$(date) on ${env.NODE_NAME}" >> ${SHARED_DATA_PATH}/logs/verification_pipeline.log
            """
            
            sh """
                find ${SHARED_DATA_PATH} -name 'trigger_verification-pipeline_*' -mmin +60 -delete 2>/dev/null || echo 'No old trigger files'
            """
        }
        
        success {
            echo "Verification pipeline succeeded on ${env.NODE_NAME}"
            
            sh """
                curl -s -X POST ${ROBOT_SYSTEM_URL}/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["Pipeline Success"], "sensor_id": "JENKINS_VERIFICATION_${env.NODE_NAME}"}' || echo 'Success notification failed'
            """
        }
        
        failure {
            echo "Verification pipeline failed on ${env.NODE_NAME}"
            
            sh """
                curl -s -X POST ${ROBOT_SYSTEM_URL}/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["Pipeline Failure"], "sensor_id": "JENKINS_VERIFICATION_${env.NODE_NAME}"}' || echo 'Failure alert failed'
            """
        }
    }
}
