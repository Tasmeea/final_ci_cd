#!/bin/bash

echo "=== Setting up Jenkins Master Node (18.143.157.100) ==="

# Update system
sudo yum update -y

# Install Docker if not already installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo yum install -y docker
    sudo service docker start
    sudo usermod -a -G docker ec2-user
    echo "Docker installed successfully"
fi

# Install Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose installed successfully"
fi

# Create project directory
sudo mkdir -p /opt/sarawak-energy
sudo chown ec2-user:ec2-user /opt/sarawak-energy
cd /opt/sarawak-energy

# Set up shared data directory
mkdir -p shared-data/{archive,logs,reports,temp}
mkdir -p database-data

# Create master node services compose file
cat > docker-compose-master.yml << 'EOF'
version: '3.8'

services:
  postgres:
    image: postgres:13
    container_name: sarawak-postgres-db
    environment:
      - POSTGRES_DB=visitors
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=sarawak2024!
    volumes:
      - ./database-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    networks:
      - sarawak-network
    restart: unless-stopped

  redis:
    image: redis:6
    container_name: sarawak-redis-cache
    ports:
      - "6379:6379"
    networks:
      - sarawak-network
    restart: unless-stopped

networks:
  sarawak-network:
    driver: bridge
EOF

# Create environment file
cat > .env << 'EOF'
# Jenkins Master Configuration
JENKINS_URL=http://18.143.157.100:8080

# Database Configuration
DB_HOST=18.143.157.100
DB_PORT=5432
DB_NAME=visitors
DB_USER=postgres
DB_PASSWORD=sarawak2024!

# Service URLs
VERIFICATION_URL=http://18.143.157.100:5001
SENSOR_ML_URL=http://18.143.157.100:5002
ROBOT_SYSTEM_URL=http://18.143.157.100:5003

# Master Node Information
NODE_NAME=jenkins-master
NODE_TYPE=ec2-master
EOF

# Start master services
echo "Starting master services..."
docker-compose -f docker-compose-master.yml up -d

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 30

# Verify services are running
echo "Verifying services..."
docker ps

# Test database connection
echo "Testing database connection..."
docker exec sarawak-postgres-db psql -U postgres -d visitors -c "SELECT version();"

# Create monitoring script
cat > monitor-system.sh << 'EOF'
#!/bin/bash

echo "=== Sarawak Energy System Health Check ==="
echo "Timestamp: $(date)"

# Check services
services=("sarawak-postgres-db" "sarawak-redis-cache")
for service in "${services[@]}"; do
    if docker ps | grep -q "$service"; then
        echo "✓ $service: Running"
    else
        echo "✗ $service: Stopped"
    fi
done

# Check endpoints
endpoints=("http://localhost:5001/health" "http://localhost:5002/health" "http://localhost:5003/health")
for endpoint in "${endpoints[@]}"; do
    if curl -s -f "$endpoint" > /dev/null; then
        echo "✓ $endpoint: Healthy"
    else
        echo "✗ $endpoint: Unhealthy"
    fi
done

echo "================================="
EOF

chmod +x monitor-system.sh

# Create backup script
cat > backup-system.sh << 'EOF'
#!/bin/bash

BACKUP_DIR="/opt/sarawak-energy/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup database
echo "Backing up database..."
docker exec sarawak-postgres-db pg_dump -U postgres visitors > "$BACKUP_DIR/database_backup.sql"

# Backup shared data
echo "Backing up shared data..."
tar -czf "$BACKUP_DIR/shared_data_backup.tar.gz" /opt/sarawak-energy/shared-data/

# Backup Jenkins data (if accessible)
if [ -d "/var/jenkins_home" ]; then
    tar -czf "$BACKUP_DIR/jenkins_backup.tar.gz" /var/jenkins_home/jobs/ /var/jenkins_home/config.xml 2>/dev/null || echo "Jenkins backup skipped"
fi

echo "Backup completed: $BACKUP_DIR"

# Keep only last 7 days of backups
find /opt/sarawak-energy/backups/ -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
EOF

chmod +x backup-system.sh

# Set up cron jobs
echo "Setting up monitoring cron job..."
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/sarawak-energy/monitor-system.sh >> /opt/sarawak-energy/logs/health.log 2>&1") | crontab -

echo "Setting up backup cron job..."
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/sarawak-energy/backup-system.sh >> /opt/sarawak-energy/logs/backup.log 2>&1") | crontab -

# Create README
cat > README.md << 'EOF'
# Sarawak Energy CI/CD - Master Node

## Services Running on Master Node:
- PostgreSQL Database (Port 5432)
- Redis Cache (Port 6379)
- Jenkins Master (Port 8080)

## Management Scripts:
- `monitor-system.sh` - Health check all services
- `backup-system.sh` - Backup database and shared data
- `docker-compose-master.yml` - Service definitions

## Service URLs:
- Jenkins: http://18.143.157.100:8080
- Database: 18.143.157.100:5432
- Redis: 18.143.157.100:6379

## Commands:
```bash
# Check service status
docker ps

# View logs
docker-compose -f docker-compose-master.yml logs

# Restart services
docker-compose -f docker-compose-master.yml restart

# Stop all services
docker-compose -f docker-compose-master.yml down

# Health check
./monitor-system.sh

# Manual backup
./backup-system.sh
```
EOF

echo ""
echo "✅ Master Node setup completed!"
echo ""
echo "Services started:"
echo "- PostgreSQL Database: localhost:5432"
echo "- Redis Cache: localhost:6379"
echo ""
echo "Next steps:"
echo "1. Access Jenkins at http://18.143.157.100:8080"
echo "2. Set up worker nodes"
echo "3. Configure Jenkins pipelines"
echo "4. Deploy application services"
echo ""
echo "Run ./monitor-system.sh to check system health"
