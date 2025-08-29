pipeline {
    agent { label 'worker-node-ec2' }
    
    environment {
        DOCKER_REGISTRY = 'localhost:5000'
        APP_NAME = 'verification-system'
        SHARED_DATA_PATH = '/opt/sarawak-energy/shared-data'
        VISITOR_RECORDS_PATH = '/opt/sarawak-energy/visitor-records'
        JENKINS_MASTER_URL = 'http://18.143.157.100:8080'
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
                        mkdir -p ${VISITOR_RECORDS_PATH}
                        mkdir -p /opt/sarawak-energy/visitor-images
                        chmod -R 755 ${SHARED_DATA_PATH} ${VISITOR_RECORDS_PATH}
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
                                -v /opt/sarawak-energy/visitor-images:/app/visitor-images \\
                                -v ${VISITOR_RECORDS_PATH}:/app/visitor-records \\
                                -e ROBOT_SYSTEM_URL=${ROBOT_SYSTEM_URL} \\
                                -e JENKINS_URL=${JENKINS_MASTER_URL} \\
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
                                
                                // Validate visitor data
                                if (visitorData.visitor_id && visitorData.name && visitorData.destination_floor) {
                                    echo "Visitor data valid: ID ${visitorData.visitor_id}"
                                    
                                    // Send notification to robot system
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
                                } else {
                                    echo "Invalid visitor data in file: ${file}"
                                }
                                
                            } catch (Exception e) {
                                echo "Error processing visitor file ${file}: ${e.getMessage()}"
                            }
                        }
                    }
                }
            }
        }
        
        stage('Generate Visitor Statistics') {
            when {
                environment name: 'NEW_VISITORS', value: 'true'
            }
            steps {
                script {
                    echo "Generating visitor statistics..."
                    
                    // Generate daily statistics
                    def today = new Date().format('yyyy-MM-dd')
                    def statsFile = "${VISITOR_RECORDS_PATH}/daily_stats_${today}.json"
                    
                    sh """
                        # Count today's visitors
                        VISITOR_COUNT=\$(find ${VISITOR_RECORDS_PATH} -name 'visitor_*.json' -newermt '${today}' | wc -l)
                        
                        # Generate statistics file
                        cat > ${statsFile} << EOF
{
  "date": "${today}",
  "total_visitors": \$VISITOR_COUNT,
  "generated_at": "\$(date -Iseconds)",
  "generated_by": "jenkins-pipeline"
}
EOF
                    """
                    
                    echo "Statistics generated for ${today}"
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
                        
                        # Move processed visitor files to archive
                        find ${SHARED_DATA_PATH} -name 'visitor_*.json' -type f -exec mv {} ${archiveDir}/ \\; 2>/dev/null || echo 'No files to archive'
                        
                        # Create processing log
                        echo "Processed at \$(date) on ${env.NODE_NAME}" >> ${archiveDir}/processing_log.txt
                        echo "Files processed: \$(ls -1 ${archiveDir}/visitor_*.json 2>/dev/null | wc -l)" >> ${archiveDir}/processing_log.txt
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
                        
                        // Test additional endpoints
                        def stats = sh(
                            script: "curl -s http://localhost:5001/stats || echo 'failed'",
                            returnStdout: true
                        ).trim()
                        
                        if (!stats.contains('failed')) {
                            echo "Statistics endpoint working"
                        }
                    } else {
                        echo "Verification system health check failed"
                        env.SYSTEM_HEALTHY = 'false'
                    }
                    
                    // Check storage directories
                    sh """
                        echo "Storage check:"
                        du -sh ${VISITOR_RECORDS_PATH} 2>/dev/null || echo "Visitor records: Not found"
                        du -sh /opt/sarawak-energy/visitor-images 2>/dev/null || echo "Visitor images: Not found"
                        du -sh ${SHARED_DATA_PATH} 2>/dev/null || echo "Shared data: Not found"
                    """
                }
            }
        }
        
        stage('Data Cleanup') {
            steps {
                script {
                    echo "Performing data cleanup..."
                    
                    sh """
                        # Clean old trigger files (older than 2 hours)
                        find ${SHARED_DATA_PATH} -name 'trigger_verification-pipeline_*' -mmin +120 -delete 2>/dev/null || echo 'No old trigger files'
                        
                        # Clean old archived data (older than 30 days)
                        find ${SHARED_DATA_PATH}/archive -name '*.json' -mtime +30 -delete 2>/dev/null || echo 'No old archive files'
                        
                        # Clean old visitor images (older than 60 days)
                        find /opt/sarawak-energy/visitor-images -name '*.jpg' -mtime +60 -delete 2>/dev/null || echo 'No old image files'
                    """
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
            
            // Archive pipeline logs
            sh """
                mkdir -p ${SHARED_DATA_PATH}/logs/pipeline-history
                echo "Build: ${BUILD_NUMBER}, Status: \${BUILD_STATUS:-UNKNOWN}, Node: ${env.NODE_NAME}, Time: \$(date)" >> ${SHARED_DATA_PATH}/logs/pipeline-history/verification_history.log
            """
        }
        
        success {
            echo "Verification pipeline succeeded on ${env.NODE_NAME}"
            
            // Send success notification to robot system
            sh """
                curl -s -X POST ${ROBOT_SYSTEM_URL}/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'\$(date -Iseconds)'", "violations": ["Pipeline Success"], "sensor_id": "JENKINS_VERIFICATION_${env.NODE_NAME}"}' || echo 'Success notification failed'
            """
        }
        
        failure {
            echo "Verification pipeline failed on ${env.NODE_NAME}"
            
            // Send failure alert to robot system
            sh """
                curl -s -X POST ${ROBOT_SYSTEM_URL}/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'\$(date -Iseconds)'", "violations": ["Pipeline Failure"], "sensor_id": "JENKINS_VERIFICATION_${env.NODE_NAME}"}' || echo 'Failure alert failed'
            """
        }
    }
}
