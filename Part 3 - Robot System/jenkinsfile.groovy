pipeline {
    agent { label 'worker-node-ec2' }
    
    environment {
        JENKINS_MASTER_URL = 'http://18.143.157.100:8080'
        SHARED_DATA_PATH = '/opt/sarawak-energy/shared-data'
        ROBOT_SYSTEM_URL = 'http://localhost:5003'
    }
    
    triggers {
        pollSCM('*/30 * * * * *')
    }
    
    stages {
        stage('Setup Robot Environment') {
            steps {
                echo "Setting up robot environment on ${env.NODE_NAME}"
                
                sh """
                    mkdir -p ${SHARED_DATA_PATH}/{robot-data,coordination,logs}
                    chmod -R 755 ${SHARED_DATA_PATH}
                """
            }
        }
        
        stage('Check Robot Triggers') {
            steps {
                script {
                    def triggerFiles = sh(
                        script: "find ${SHARED_DATA_PATH} -name 'trigger_robot-*' -newer /tmp/last_robot_check 2>/dev/null || echo 'none'",
                        returnStdout: true
                    ).trim()
                    
                    if (triggerFiles != 'none' && triggerFiles != '') {
                        echo "Robot triggers detected: ${triggerFiles}"
                        env.ROBOT_TRIGGERED = 'true'
                        sh "touch /tmp/last_robot_check"
                        
                        if (triggerFiles.contains('robot-pipeline')) {
                            env.TRIGGER_TYPE = 'visitor'
                        } else if (triggerFiles.contains('robot-threshold-response')) {
                            env.TRIGGER_TYPE = 'threshold'
                        } else {
                            env.TRIGGER_TYPE = 'general'
                        }
                        
                        echo "Trigger type: ${env.TRIGGER_TYPE}"
                    } else {
                        echo "No robot triggers found"
                        env.ROBOT_TRIGGERED = 'false'
                    }
                }
            }
        }
        
        stage('Deploy Robot System') {
            steps {
                script {
                    echo "Deploying robot system on ${env.NODE_NAME}..."
                    
                    def isRunning = sh(
                        script: "docker ps | grep sarawak-robot-controller || echo 'not_running'",
                        returnStdout: true
                    ).trim()
                    
                    if (isRunning.contains('not_running')) {
                        sh """
                            docker run -d \\
                                --name sarawak-robot-controller \\
                                --network sarawak-network \\
                                -p 5003:5000 \\
                                -v ${SHARED_DATA_PATH}:/app/shared-data \\
                                --restart unless-stopped \\
                                sarawak-robot:latest || echo 'Robot container start failed'
                        """
                        sleep(20)
                    }
                }
            }
        }
        
        stage('Process Visitor Updates') {
            when {
                allOf {
                    environment name: 'ROBOT_TRIGGERED', value: 'true'
                    environment name: 'TRIGGER_TYPE', value: 'visitor'
                }
            }
            steps {
                script {
                    echo "Processing visitor updates for robots..."
                    
                    def visitorFiles = sh(
                        script: "find ${SHARED_DATA_PATH}/archive -name 'visitor_*.json' -mmin -60 -type f | head -10",
                        returnStdout: true
                    ).trim().split('\n')
                    
                    for (file in visitorFiles) {
                        if (file.trim()) {
                            echo "Processing visitor file for robots: ${file}"
                            
                            def visitorData = readJSON file: file
                            echo "Updating robot patrol for visitor: ${visitorData.name} on floor ${visitorData.destination_floor}"
                            
                            sh """
                                curl -X POST http://robot-system:5000/check_visitor_access \\
                                -H 'Content-Type: application/json' \\
                                -d '{"visitor_id": "${visitorData.visitor_id}", "current_floor": ${visitorData.destination_floor}}' || echo 'Robot update failed'
                            """
                        }
                    }
                }
            }
        }
        
        stage('Handle Threshold Response') {
            when {
                allOf {
                    environment name: 'ROBOT_TRIGGERED', value: 'true'
                    environment name: 'TRIGGER_TYPE', value: 'threshold'
                }
            }
            steps {
                script {
                    echo "Processing threshold response..."
                    
                    def alertFiles = sh(
                        script: "find ${SHARED_DATA_PATH} -name 'alert_*.json' -mmin -30 -type f",
                        returnStdout: true
                    ).trim().split('\n')
                    
                    for (file in alertFiles) {
                        if (file.trim()) {
                            echo "Processing alert file: ${file}"
                            
                            def alertData = readJSON file: file
                            echo "Alert violations: ${alertData.violations}"
                            
                            if (alertData.violations.any { it.contains('Temperature') }) {
                                echo "Initiating robot temperature control response"
                                
                                sleep(5)
                                
                                sh """
                                    echo "{
                                        \\"timestamp\\": \\"`date -Iseconds`\\",
                                        \\"robot_id\\": \\"ROBOT_002\\",
                                        \\"action\\": \\"temperature_adjustment\\",
                                        \\"sensor_id\\": \\"${alertData.sensor_id}\\",
                                        \\"status\\": \\"completed\\"
                                    }" > ${SHARED_DATA_PATH}/robot_action_`date +%s`.json
                                """
                                
                                echo "Robot temperature adjustment completed"
                            }
                        }
                    }
                }
            }
        }
        
        stage('Update Robot Dashboard') {
            when {
                environment name: 'ROBOT_TRIGGERED', value: 'true'
            }
            steps {
                script {
                    echo "Updating robot dashboard..."
                    
                    def dashboardData = sh(
                        script: "curl -s http://robot-system:5000/api/dashboard_data || echo '{}'",
                        returnStdout: true
                    ).trim()
                    
                    if (!dashboardData.contains('error')) {
                        echo "Dashboard updated successfully"
                        
                        def timestamp = new Date().format('yyyy-MM-dd_HH-mm-ss')
                        writeFile file: "/workspace/reports/dashboard_${timestamp}.json", text: dashboardData
                        
                        echo "Dashboard report saved"
                    } else {
                        echo "Dashboard update failed"
                    }
                }
            }
        }
        
        stage('System Health Check') {
            steps {
                script {
                    echo "Performing robot system health check..."
                    
                    def services = ['verification-system', 'sensor-ml-system', 'robot-system']
                    def healthStatus = [:]
                    
                    for (service in services) {
                        def health = sh(
                            script: "curl -s http://18.143.157.100:5001/health || echo 'failed'",
                            returnStdout: true
                        ).trim()
                        
                        healthStatus[service] = health.contains('healthy') ? 'healthy' : 'unhealthy'
                        echo "${service}: ${healthStatus[service]}"
                    }
                    
                    def healthReport = [
                        timestamp: new Date().format('yyyy-MM-dd HH:mm:ss'),
                        services: healthStatus,
                        overall_status: healthStatus.values().every { it == 'healthy' } ? 'healthy' : 'degraded'
                    ]
                    
                    writeJSON file: '/workspace/reports/health_check.json', json: healthReport
                    echo "Health check completed: ${healthReport.overall_status}"
                    
                    env.SYSTEM_HEALTHY = healthReport.overall_status == 'healthy' ? 'true' : 'false'
                }
            }
        }
        
        stage('Performance Monitoring') {
            steps {
                script {
                    echo "Monitoring system performance..."
                    
                    sh """
                        docker stats --no-stream --format 'table {{.Container}}\\t{{.CPUPerc}}\\t{{.MemUsage}}' > /workspace/reports/container_stats.txt 2>/dev/null || echo 'Stats unavailable'
                    """
                    
                    def diskUsage = sh(
                        script: "du -sh ${SHARED_DATA_PATH} | cut -f1",
                        returnStdout: true
                    ).trim()
                    
                    echo "Shared data disk usage: ${diskUsage}"
                    
                    sh """
                        find ${SHARED_DATA_PATH}/archive -name '*.json' -mtime +7 -delete 2>/dev/null || echo 'No old files to clean'
                        find ${SHARED_DATA_PATH} -name 'trigger_*' -mmin +180 -delete 2>/dev/null || echo 'No old triggers to clean'
                    """
                }
            }
        }
    }
    
    post {
        always {
            echo "Robot pipeline completed"
            
            sh """
                mkdir -p /workspace/logs/robot-pipeline
                echo "Pipeline completed at `date`" > /workspace/logs/robot-pipeline/pipeline_`date +%Y%m%d_%H%M%S`.log
            """
            
            sh """
                find ${SHARED_DATA_PATH} -name 'trigger_robot-*' -mmin +90 -delete 2>/dev/null || echo 'No old trigger files'
            """
        }
        
        success {
            echo "Robot pipeline succeeded"
            
            sh """
                curl -X POST http://robot-system:5000/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["Pipeline Success"], "sensor_id": "JENKINS_ROBOT", "all_parameters": {"status": "success"}}' || echo 'Notification failed'
            """
        }
        
        failure {
            echo "Robot pipeline failed"
            
            sh """
                curl -X POST http://robot-system:5000/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["Robot Pipeline Failure"], "sensor_id": "JENKINS_ROBOT"}' || echo 'Alert failed'
            """
        }
        
        unstable {
            echo "Robot pipeline unstable"
            
            sh """
                curl -X POST http://robot-system:5000/threshold_alert \\
                -H 'Content-Type: application/json' \\
                -d '{"timestamp": "'$(date -Iseconds)'", "violations": ["Pipeline Unstable"], "sensor_id": "JENKINS_ROBOT"}' || echo 'Warning failed'
            """
        }
    }
}