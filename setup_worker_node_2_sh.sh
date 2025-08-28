#!/bin/bash

echo "=== Setting up Worker Node 2 (EC2 Worker) ==="

# Update system
sudo yum update -y

# Install required packages
sudo yum install -y docker git java-11-openjdk curl wget

# Start Docker
sudo service docker start
sudo usermod -a -G docker ec2-user

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create project structure
sudo mkdir -p /opt/sarawak-energy/{jenkins-workspace,shared-data,visitor-images,logs,reports}
sudo chown ec2-user:ec2-user /opt/sarawak-energy
mkdir -p /opt/sarawak-energy/shared-data/{archive,coordination,robot-data}

# Create environment configuration
cat > /opt/sarawak-energy/.env << EOF
# Jenkins Configuration
JENKINS_URL=http://18.143.157.100:8080
NODE_NAME=worker-node-ec2
NODE_TYPE=ec2-worker

# Master Node Services
DB_HOST=18.143.157.100
DB_PORT=5432
REDIS_HOST=18.143.157.100
REDIS_PORT=6379

# Service Ports
VERIFICATION_PORT=5001
ROBOT_SYSTEM_PORT=5003
ML_SYSTEM_URL=http://18.143.157.100:5002

# Paths
SHARED_DATA_PATH=/opt/sarawak-energy/shared-data
VISITOR_IMAGES_PATH=/opt/sarawak-energy/visitor-images

# Docker Configuration
DOCKER_NETWORK=sarawak-network
EOF

# Create Docker network
docker network create sarawak-network 2>/dev/null || echo "Network already exists"

# Create Jenkins agent startup script
cat > /opt/sarawak-energy/start-jenkins-agent.sh << 'EOF'
#!/bin/bash

JENKINS_URL="http://18.143.157.100:8080"
NODE_NAME="worker-node-ec2"
SECRET=""  # Get this from Jenkins UI after adding the node

if [ -z "$SECRET" ]; then
    echo "Please set the SECRET variable in this script."
    echo "Get the secret from Jenkins UI: Manage Jenkins > Manage Nodes > worker-node-ec2 > Configure"
    exit 1
fi

# Download agent JAR
curl -o /opt/sarawak-energy/agent.jar ${JENKINS_URL}/jnlpJars/agent.jar

# Start Jenkins agent
java -jar /opt/sarawak-energy/agent.jar \
    -jnlpUrl ${JENKINS_URL}/computer/${NODE_NAME}/slave-agent.jnlp \
    -secret ${SECRET} \
    -workDir /opt/sarawak-energy/jenkins-workspace
EOF

chmod +x /opt/sarawak-energy/start-jenkins-agent.sh

# Create service deployment script
cat > /opt/sarawak-energy/deploy-web-services.sh << 'EOF'
#!/bin/bash

echo "Deploying Web Services on Worker Node 2..."

# Load environment
source /opt/sarawak-energy/.env

# Check if source code exists
if [ ! -d "/opt/sarawak-energy/sarawak-project" ]; then
    echo "Project source code not found. Please clone the repository:"
    echo "cd /opt/sarawak-energy && git clone <your-repo-url> sarawak-project"
    exit 1
fi

cd /opt/sarawak-energy/sarawak-project

echo "Building Verification System..."
cd part1-verification
docker build -t sarawak-verification:latest .

echo "Building Robot System..."
cd ../part3-robots
docker build -t sarawak-robot:latest .

cd /opt/sarawak-energy

echo "Deploying Verification System..."

# Deploy Verification System
docker stop sarawak-verification-kiosk 2>/dev/null || true
docker rm sarawak-verification-kiosk 2>/dev/null || true

docker run -d \
    --name sarawak-verification-kiosk \
    --network ${DOCKER_NETWORK} \
    -p ${VERIFICATION_PORT}:5000 \
    -v ${SHARED_DATA_PATH}:/app/shared-data \
    -v ${VISITOR_IMAGES_PATH}:/app/visitor-images \
    -e DATABASE_URL=postgresql://postgres:sarawak2024!@${DB_HOST}:${DB_PORT}/visitors \
    -e ROBOT_SYSTEM_URL=http://localhost:${ROBOT_SYSTEM_PORT} \
    --restart unless-stopped \
    sarawak-verification:latest

echo "Deploying Robot System..."

# Deploy Robot System
docker stop sarawak-robot-controller 2>/dev/null || true
docker rm sarawak-robot-controller 2>/dev/null || true

docker run -d \
    --name sarawak-robot-controller \
    --network ${DOCKER_NETWORK} \
    -p ${ROBOT_SYSTEM_PORT}:5000 \
    -v ${SHARED_DATA_PATH}:/app/shared-data \
    -e ML_SYSTEM_URL=${ML_SYSTEM_URL} \
    --restart unless-stopped \
    sarawak-robot:latest

echo "Web Services deployed successfully!"
echo "Verification System: http://$(curl -s http://checkip.amazonaws.com):${VERIFICATION_PORT}"
echo "Robot Dashboard: http://$(curl -s http://checkip.amazonaws.com):${ROBOT_SYSTEM_PORT}"
EOF

chmod +x /opt/sarawak-energy/deploy-web-services.sh

# Create service management script
cat > /opt/sarawak-energy/manage-services.sh << 'EOF'
#!/bin/bash

case $1 in
    start)
        echo "Starting all services..."
        docker start sarawak-verification-kiosk sarawak-robot-controller
        ;;
    stop)
        echo "Stopping all services..."
        docker stop sarawak-verification-kiosk sarawak-robot-controller
        ;;
    restart)
        echo "Restarting all services..."
        docker restart sarawak-verification-kiosk sarawak-robot-controller
        ;;
    status)
        echo "Service status:"
        docker ps -f name=sarawak-
        ;;
    logs)
        echo "Service logs:"
        docker logs sarawak-verification-kiosk --tail=50
        echo "--- Robot System ---"
        docker logs sarawak-robot-controller --tail=50
        ;;
    health)
        echo "Health check:"
        curl -s http://localhost:5001/health || echo "Verification system: Unhealthy"
        curl -s http://localhost:5003/health || echo "Robot system: Unhealthy"
        ;;
    build)
        echo "Building and deploying services..."
        ./deploy-web-services.sh
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|health|build}"
        exit 1
        ;;
esac
EOF

chmod +x /opt/sarawak-energy/manage-services.sh

# Create monitoring script
cat > /opt/sarawak-energy/monitor-worker2.sh << 'EOF'
#!/bin/bash

echo "=== Worker Node 2 Health Check ==="
echo "Timestamp: $(date)"

# Check containers
services=("sarawak-verification-kiosk" "sarawak-robot-controller")
for service in "${services[@]}"; do
    if docker ps | grep -q "$service"; then
        echo "✓ $service: Running"
    else
        echo "✗ $service: Not Running"
    fi
done

# Check service endpoints
endpoints=("http://localhost:5001/health" "http://localhost:5003/health")
for endpoint in "${endpoints[@]}"; do
    if curl -s -f "$endpoint" > /dev/null; then
        echo "✓ $endpoint: Healthy"
    else
        echo "✗ $endpoint: Unhealthy"
    fi
done

# Check disk usage
echo "Disk Usage:"
df -h /opt/sarawak-energy

# Check memory usage
echo "Memory Usage:"
free -h

echo "================================="
EOF

chmod +x /opt/sarawak-energy/monitor-worker2.sh

# Create backup script
cat > /opt/sarawak-energy/backup-worker2.sh << 'EOF'
#!/bin/bash

BACKUP_DIR="/opt/sarawak-energy/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up Worker Node 2 data..."

# Backup shared data
tar -czf "$BACKUP_DIR/shared_data_backup.tar.gz" /opt/sarawak-energy/shared-data/

# Backup visitor images
tar -czf "$BACKUP_DIR/visitor_images_backup.tar.gz" /opt/sarawak-energy/visitor-images/ 2>/dev/null || true

# Backup logs
tar -czf "$BACKUP_DIR/logs_backup.tar.gz" /opt/sarawak-energy/logs/

echo "Backup completed: $BACKUP_DIR"

# Keep only last 5 backups
ls -t /opt/sarawak-energy/backups/ | tail -n +6 | xargs -r rm -rf
EOF

chmod +x /opt/sarawak-energy/backup-worker2.sh

# Create cleanup script
cat > /opt/sarawak-energy/cleanup-worker2.sh << 'EOF'
#!/bin/bash

echo "Cleaning up Worker Node 2..."

# Clean old visitor images (older than 30 days)
find /opt/sarawak-energy/visitor-images -name "*.jpg" -mtime +30 -delete 2>/dev/null
echo "Cleaned old visitor images"

# Clean old shared data (older than 7 days)
find /opt/sarawak-energy/shared-data/archive -name "*.json" -mtime +7 -delete 2>/dev/null
echo "Cleaned old shared data"

# Clean Docker system
docker system prune -f
echo "Cleaned Docker system"

# Clean logs (older than 30 days)
find /opt/sarawak-energy/logs -name "*.log" -mtime +30 -delete 2>/dev/null
echo "Cleaned old logs"

echo "Cleanup completed!"
EOF

chmod +x /opt/sarawak-energy/cleanup-worker2.sh

# Set up cron jobs
echo "Setting up cron jobs..."
(crontab -l 2>/dev/null; echo "*/10 * * * * /opt/sarawak-energy/monitor-worker2.sh >> /opt/sarawak-energy/logs/health.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/sarawak-energy/backup-worker2.sh >> /opt/sarawak-energy/logs/backup.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 4 * * * /opt/sarawak-energy/cleanup-worker2.sh >> /opt/sarawak-energy/logs/cleanup.log 2>&1") | crontab -

# Create README
cat > /opt/sarawak-energy/README-worker2.md << 'EOF'
# Sarawak Energy CI/CD - Worker Node 2 (Web Services)

## Services:
- Verification System (Visitor Kiosk) - Port 5001
- Robot Control System (Dashboard) - Port 5003
- Jenkins Agent

## Setup Steps:
1. Clone project repository:
   ```bash
   cd /opt/sarawak-energy
   git clone <your-repo-url> sarawak-project
   ```

2. Deploy web services:
   ```bash
   ./deploy-web-services.sh
   ```

3. Configure Jenkins agent secret in start-jenkins-agent.sh

4. Start Jenkins agent:
   ```bash
   ./start-jenkins-agent.sh
   ```

## Management Commands:
```bash
# Manage services
./manage-services.sh {start|stop|restart|status|logs|health|build}

# Monitor system
./monitor-worker2.sh

# Backup data
./backup-worker2.sh

# Clean up old data
./cleanup-worker2.sh
```

## Access URLs:
- Verification System: http://[EC2-IP]:5001
- Robot Dashboard: http://[EC2-IP]:5003

## Directories:
- `/opt/sarawak-energy/shared-data` - Shared data with other nodes
- `/opt/sarawak-energy/visitor-images` - Visitor photos by date
- `/opt/sarawak-energy/logs` - System logs
- `/opt/sarawak-energy/jenkins-workspace` - Jenkins workspace
EOF

echo ""
echo "✅ Worker Node 2 setup completed!"
echo ""
echo "Next steps:"
echo "1. Clone the project repository:"
echo "   cd /opt/sarawak-energy && git clone <your-repo-url> sarawak-project"
echo ""
echo "2. Deploy web services:"
echo "   ./deploy-web-services.sh"
echo ""
echo "3. Add Jenkins node in Jenkins UI and get the secret"
echo "4. Update start-jenkins-agent.sh with the secret"
echo "5. Start Jenkins agent: ./start-jenkins-agent.sh"
echo ""
echo "Management scripts available:"
echo "- ./manage-services.sh - Manage web services"
echo "- ./monitor-worker2.sh - Health check"
echo "- ./backup-worker2.sh - Backup data"
echo "- ./cleanup-worker2.sh - Clean old data"
echo ""
echo "Services will be available at:"
echo "- Verification: http://$(curl -s http://checkip.amazonaws.com 2>/dev/null || echo 'YOUR-EC2-IP'):5001"
echo "- Robot Dashboard: http://$(curl -s http://checkip.amazonaws.com 2>/dev/null || echo 'YOUR-EC2-IP'):5003"