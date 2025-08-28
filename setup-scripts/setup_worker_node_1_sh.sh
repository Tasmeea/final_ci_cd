#!/bin/bash

echo "=== Setting up Worker Node 1 (Linux-Docker) ==="

# Create Jenkins workspace
sudo mkdir -p /opt/sarawak-energy/jenkins-workspace
sudo chown $USER:$USER /opt/sarawak-energy/jenkins-workspace

# Create project directories
mkdir -p /opt/sarawak-energy/{shared-data,models,logs,temp}
mkdir -p /opt/sarawak-energy/shared-data/{archive,ml-data,triggers}

# Install required tools
sudo apt-get update
sudo apt-get install -y curl wget git python3 python3-pip openjdk-11-jdk

# Install Docker if not already installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    echo "Docker installed. Please log out and log back in for group changes to take effect."
fi

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create environment file
cat > /opt/sarawak-energy/.env << EOF
# Jenkins Configuration
JENKINS_URL=http://18.143.157.100:8080
NODE_NAME=worker
NODE_TYPE=linux-docker

# Master Node Services
DB_HOST=18.143.157.100
DB_PORT=5432
REDIS_HOST=18.143.157.100
REDIS_PORT=6379

# Service URLs
VERIFICATION_URL=http://18.143.157.100:5001
ROBOT_SYSTEM_URL=http://18.143.157.100:5003

# ML Configuration
ML_PORT=5002
MODEL_PATH=/opt/sarawak-energy/models
SENSOR_DATA_PATH=/opt/sarawak-energy/shared-data

# Docker Configuration
DOCKER_NETWORK=sarawak-network
EOF

# Create Docker network
docker network create sarawak-network 2>/dev/null || echo "Network already exists"

# Create Jenkins agent startup script
cat > /opt/sarawak-energy/start-jenkins-agent.sh << 'EOF'
#!/bin/bash

JENKINS_URL="http://18.143.157.100:8080"
NODE_NAME="worker"
SECRET=""  # Get this from Jenkins UI after adding the node

if [ -z "$SECRET" ]; then
    echo "Please set the SECRET variable in this script."
    echo "Get the secret from Jenkins UI: Manage Jenkins > Manage Nodes > worker > Configure"
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

# Create ML system deployment script
cat > /opt/sarawak-energy/deploy-ml-system.sh << 'EOF'
#!/bin/bash

echo "Deploying ML System on Worker Node 1..."

# Load environment
source /opt/sarawak-energy/.env

# Check if source code exists
if [ ! -d "/opt/sarawak-energy/sarawak-project" ]; then
    echo "Project source code not found. Please clone the repository:"
    echo "cd /opt/sarawak-energy && git clone <your-repo-url> sarawak-project"
    exit 1
fi

# Build ML image
cd /opt/sarawak-energy/sarawak-project/part2-sensor-ml
docker build -t sarawak-sensor-ml:latest .

# Stop existing container
docker stop sarawak-sensor-ml-pipeline 2>/dev/null || true
docker rm sarawak-sensor-ml-pipeline 2>/dev/null || true

# Run ML container
docker run -d \
    --name sarawak-sensor-ml-pipeline \
    --network ${DOCKER_NETWORK} \
    -p ${ML_PORT}:5000 \
    -v ${SENSOR_DATA_PATH}:/app/shared-data \
    -v ${MODEL_PATH}:/app/models \
    -e ROBOT_SYSTEM_URL=${ROBOT_SYSTEM_URL} \
    -e DATABASE_URL=postgresql://postgres:sarawak2024!@${DB_HOST}:${DB_PORT}/visitors \
    --memory=2g \
    --cpus=2 \
    --restart unless-stopped \
    sarawak-sensor-ml:latest

echo "ML System deployed successfully!"
echo "Health check: curl http://localhost:${ML_PORT}/health"
EOF

chmod +x /opt/sarawak-energy/deploy-ml-system.sh

# Create system management script
cat > /opt/sarawak-energy/manage-ml.sh << 'EOF'
#!/bin/bash

case $1 in
    start)
        echo "Starting ML system..."
        docker start sarawak-sensor-ml-pipeline
        ;;
    stop)
        echo "Stopping ML system..."
        docker stop sarawak-sensor-ml-pipeline
        ;;
    restart)
        echo "Restarting ML system..."
        docker restart sarawak-sensor-ml-pipeline
        ;;
    status)
        echo "ML system status:"
        docker ps -f name=sarawak-sensor-ml-pipeline
        ;;
    logs)
        echo "ML system logs:"
        docker logs sarawak-sensor-ml-pipeline --tail=50
        ;;
    health)
        echo "ML system health check:"
        curl -s http://localhost:5002/health || echo "Health check failed"
        ;;
    build)
        echo "Building ML system..."
        ./deploy-ml-system.sh
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|health|build}"
        exit 1
        ;;
esac
EOF

chmod +x /opt/sarawak-energy/manage-ml.sh

# Create monitoring script
cat > /opt/sarawak-energy/monitor-worker1.sh << 'EOF'
#!/bin/bash

echo "=== Worker Node 1 Health Check ==="
echo "Timestamp: $(date)"

# Check ML container
if docker ps | grep -q "sarawak-sensor-ml-pipeline"; then
    echo "✓ ML Container: Running"
    
    # Check ML service health
    if curl -s -f http://localhost:5002/health > /dev/null; then
        echo "✓ ML Service: Healthy"
    else
        echo "✗ ML Service: Unhealthy"
    fi
else
    echo "✗ ML Container: Not Running"
fi

# Check disk usage
echo "Disk Usage:"
df -h /opt/sarawak-energy

# Check Docker stats
echo "Docker Stats:"
docker stats --no-stream sarawak-sensor-ml-pipeline 2>/dev/null || echo "No ML container running"

echo "================================="
EOF

chmod +x /opt/sarawak-energy/monitor-worker1.sh

# Create data cleanup script
cat > /opt/sarawak-energy/cleanup-data.sh << 'EOF'
#!/bin/bash

echo "Cleaning up old data on Worker Node 1..."

# Clean old shared data (older than 7 days)
find /opt/sarawak-energy/shared-data -name "*.json" -mtime +7 -delete 2>/dev/null
echo "Cleaned old shared data files"

# Clean old model backups (older than 14 days)
find /opt/sarawak-energy/models/backup -type d -mtime +14 -exec rm -rf {} \; 2>/dev/null
echo "Cleaned old model backups"

# Clean Docker images and containers
docker system prune -f
echo "Cleaned Docker system"

# Clean logs (older than 30 days)
find /opt/sarawak-energy/logs -name "*.log" -mtime +30 -delete 2>/dev/null
echo "Cleaned old logs"

echo "Cleanup completed!"
EOF

chmod +x /opt/sarawak-energy/cleanup-data.sh

# Set up cron jobs
echo "Setting up cron jobs..."
(crontab -l 2>/dev/null; echo "*/10 * * * * /opt/sarawak-energy/monitor-worker1.sh >> /opt/sarawak-energy/logs/health.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/sarawak-energy/cleanup-data.sh >> /opt/sarawak-energy/logs/cleanup.log 2>&1") | crontab -

# Create README
cat > /opt/sarawak-energy/README-worker1.md << 'EOF'
# Sarawak Energy CI/CD - Worker Node 1 (ML Processing)

## Services:
- ML System (Sensor Monitoring & Training) - Port 5002
- Jenkins Agent

## Setup Steps:
1. Clone project repository:
   ```bash
   cd /opt/sarawak-energy
   git clone <your-repo-url> sarawak-project
   ```

2. Deploy ML system:
   ```bash
   ./deploy-ml-system.sh
   ```

3. Configure Jenkins agent secret in start-jenkins-agent.sh

4. Start Jenkins agent:
   ```bash
   ./start-jenkins-agent.sh
   ```

## Management Commands:
```bash
# Manage ML system
./manage-ml.sh {start|stop|restart|status|logs|health|build}

# Monitor system
./monitor-worker1.sh

# Clean up old data
./cleanup-data.sh
```

## Directories:
- `/opt/sarawak-energy/shared-data` - Shared data with other nodes
- `/opt/sarawak-energy/models` - ML models and backups
- `/opt/sarawak-energy/logs` - System logs
- `/opt/sarawak-energy/jenkins-workspace` - Jenkins workspace
EOF

echo ""
echo "✅ Worker Node 1 setup completed!"
echo ""
echo "Next steps:"
echo "1. Clone the project repository:"
echo "   cd /opt/sarawak-energy && git clone <your-repo-url> sarawak-project"
echo ""
echo "2. Deploy ML system:"
echo "   ./deploy-ml-system.sh"
echo ""
echo "3. Add Jenkins node in Jenkins UI and get the secret"
echo "4. Update start-jenkins-agent.sh with the secret"
echo "5. Start Jenkins agent: ./start-jenkins-agent.sh"
echo ""
echo "Management scripts available:"
echo "- ./manage-ml.sh - Manage ML system"
echo "- ./monitor-worker1.sh - Health check"
echo "- ./cleanup-data.sh - Clean old data"
