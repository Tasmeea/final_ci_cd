#!/bin/bash

echo "=== Setting up Jenkins Master Node (18.143.157.100) - No Database ==="

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

# Set up shared data and storage directories
mkdir -p shared-data/{archive,logs,reports,temp}
mkdir -p visitor-records
mkdir -p visitor-images

# Create master node services compose file (Redis only)
cat > docker-compose-master.yml << 'EOF'
version: '3.8'

services:
  redis:
    image: redis:6
    container_name: sarawak-redis-cache
    ports:
      - "6379:6379"
    volumes:
      - ./redis-data:/data
    command: redis-server --appendonly yes
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

# Service URLs
VERIFICATION_URL=http://18.143.157.100:5001
SENSOR_ML_URL=http://18.143.157.100:5002
ROBOT_SYSTEM_URL=http://18.143.157.100:5003

# Storage Configuration
STORAGE_TYPE=file-based
SHARED_DATA_PATH=/opt/sarawak-energy/shared-data
VISITOR_RECORDS_PATH=/opt/sarawak-energy/visitor-records
VISITOR_IMAGES_PATH=/opt/sarawak-energy/visitor-images

# Master Node Information
NODE_NAME=jenkins-master
NODE_TYPE=ec2-master
EOF

# Start master services (only Redis for caching)
echo "Starting master services..."
docker-compose -f docker-compose-master.yml up -d

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 15

# Verify services are running
echo "Verifying services..."
docker ps

# Test Redis connection
echo "Testing Redis connection..."
docker exec sarawak-redis-cache redis-cli ping

# Create monitoring script
cat > monitor-system.sh << 'EOF'
#!/bin/bash

echo "=== Sarawak Energy System Health Check (File-based Storage) ==="
echo "Timestamp: $(date)"

# Check Redis service
if docker ps | grep -q "sarawak-redis-cache"; then
    echo "✓ Redis Cache: Running"
    
    # Test Redis connectivity
    if docker exec sarawak-redis-cache redis-cli ping > /dev/null 2>&1; then
        echo "✓ Redis: Responding"
    else
        echo "✗ Redis: Not responding"
    fi
else
    echo "✗ Redis Cache: Stopped"
fi

# Check storage directories
echo "Storage Status:"
if [ -d "/opt/sarawak-energy/shared-data" ]; then
    echo "✓ Shared Data: $(du -sh /opt/sarawak-energy/shared-data | cut -f1)"
else
    echo "✗ Shared Data: Missing"
fi

if [ -d "/opt/sarawak-energy/visitor-records" ]; then
    echo "✓ Visitor Records: $(find /opt/sarawak-energy/visitor-records -name '*.json' | wc -l) files"
else
    echo "✗ Visitor Records: Missing"
fi

if [ -d "/opt/sarawak-energy/visitor-images" ]; then
    echo "✓ Visitor Images: $(find /opt/sarawak-energy/visitor-images -name '*.jpg' | wc -l) files"
else
    echo "✗ Visitor Images: Missing"
fi

# Check service endpoints
endpoints=("http://localhost:5001/health" "http://localhost:5002/health" "http://localhost:5003/health")
for endpoint in "${endpoints[@]}"; do
    if curl -s -f "$endpoint" > /dev/null; then
        echo "✓ $endpoint: Healthy"
    else
        echo "✗ $endpoint: Unhealthy"
    fi
done

# Check disk space
echo "Disk Usage:"
df -h /opt/sarawak-energy | tail -1

echo "================================="
EOF

chmod +x monitor-system.sh

# Create backup script
cat > backup-system.sh << 'EOF'
#!/bin/bash

BACKUP_DIR="/opt/sarawak-energy/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up file-based system data..."

# Backup shared data
echo "Backing up shared data..."
tar -czf "$BACKUP_DIR/shared_data_backup.tar.gz" /opt/sarawak-energy/shared-data/ 2>/dev/null || echo "Shared data backup failed"

# Backup visitor records
echo "Backing up visitor records..."
tar -czf "$BACKUP_DIR/visitor_records_backup.tar.gz" /opt/sarawak-energy/visitor-records/ 2>/dev/null || echo "Visitor records backup failed"

# Backup visitor images
echo "Backing up visitor images..."
tar -czf "$BACKUP_DIR/visitor_images_backup.tar.gz" /opt/sarawak-energy/visitor-images/ 2>/dev/null || echo "Visitor images backup failed"

# Backup Redis data
echo "Backing up Redis data..."
docker exec sarawak-redis-cache redis-cli BGSAVE > /dev/null 2>&1
sleep 5
tar -czf "$BACKUP_DIR/redis_data_backup.tar.gz" /opt/sarawak-energy/redis-data/ 2>/dev/null || echo "Redis backup failed"

# Create backup manifest
cat > "$BACKUP_DIR/backup_manifest.txt" << MANIFEST
Backup Date: $(date)
Node: Master Node (18.143.157.100)
Storage Type: File-based
Components:
- Shared Data
- Visitor Records
- Visitor Images
- Redis Cache Data
MANIFEST

echo "Backup completed: $BACKUP_DIR"

# Keep only last 7 days of backups
find /opt/sarawak-energy/backups/ -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true

# Show backup size
echo "Backup size: $(du -sh $BACKUP_DIR | cut -f1)"
EOF

chmod +x backup-system.sh

# Create data maintenance script
cat > maintain-data.sh << 'EOF'
#!/bin/bash

echo "=== Data Maintenance - File-based Storage ==="

# Clean old shared data files (older than 30 days)
echo "Cleaning old shared data..."
find /opt/sarawak-energy/shared-data/archive -name "*.json" -mtime +30 -delete 2>/dev/null
echo "Cleaned archived files older than 30 days"

# Clean old visitor images (older than 90 days)
echo "Cleaning old visitor images..."
find /opt/sarawak-energy/visitor-images -name "*.jpg" -mtime +90 -delete 2>/dev/null
echo "Cleaned visitor images older than 90 days"

# Clean old log files (older than 30 days)
echo "Cleaning old logs..."
find /opt/sarawak-energy/shared-data/logs -name "*.log" -mtime +30 -delete 2>/dev/null
echo "Cleaned log files older than 30 days"

# Optimize Redis memory
echo "Optimizing Redis..."
docker exec sarawak-redis-cache redis-cli MEMORY PURGE > /dev/null 2>&1
echo "Redis memory optimized"

# Generate maintenance report
cat > /opt/sarawak-energy/shared-data/logs/maintenance_$(date +%Y%m%d).log << REPORT
Maintenance completed at: $(date)
Storage type: File-based
Visitor records: $(find /opt/sarawak-energy/visitor-records -name "*.json" | wc -l) files
Visitor images: $(find /opt/sarawak-energy/visitor-images -name "*.jpg" | wc -l) files
Shared data size: $(du -sh /opt/sarawak-energy/shared-data | cut -f1)
Disk usage: $(df -h /opt/sarawak-energy | tail -1)
REPORT

echo "Maintenance completed. Report saved to logs."
EOF

chmod +x maintain-data.sh

# Create visitor data utility script
cat > visitor-utils.sh << 'EOF'
#!/bin/bash

case $1 in
    count)
        echo "Visitor Statistics:"
        echo "Total visitor records: $(find /opt/sarawak-energy/visitor-records -name 'visitor_*.json' | wc -l)"
        echo "Visitors today: $(find /opt/sarawak-energy/visitor-records -name 'daily_visitors_'$(date +%Y-%m-%d)'.json' -exec wc -l {} \; 2>/dev/null | awk '{print $1}' || echo '0')"
        echo "Total visitor images: $(find /opt/sarawak-energy/visitor-images -name '*.jpg' | wc -l)"
        ;;
    today)
        today=$(date +%Y-%m-%d)
        daily_file="/opt/sarawak-energy/visitor-records/daily_visitors_$today.json"
        if [ -f "$daily_file" ]; then
            echo "Today's visitors ($today):"
            cat "$daily_file" | jq -r '.[] | "\(.visitor_id): \(.name) -> Floor \(.destination_floor)"' 2>/dev/null || echo "Invalid JSON format"
        else
            echo "No visitors recorded for today"
        fi
        ;;
    stats)
        echo "Storage Statistics:"
        echo "Shared data: $(du -sh /opt/sarawak-energy/shared-data 2>/dev/null | cut -f1 || echo '0B')"
        echo "Visitor records: $(du -sh /opt/sarawak-energy/visitor-records 2>/dev/null | cut -f1 || echo '0B')"
        echo "Visitor images: $(du -sh /opt/sarawak-energy/visitor-images 2>/dev/null | cut -f1 || echo '0B')"
        echo "Total project size: $(du -sh /opt/sarawak-energy 2>/dev/null | cut -f1 || echo '0B')"
        ;;
    clean)
        echo "Cleaning temporary files..."
        find /opt/sarawak-energy/shared-data/temp -type f -delete 2>/dev/null
        find /opt/sarawak-energy/shared-data -name 'trigger_*' -mmin +60 -delete 2>/dev/null
        echo "Cleanup completed"
        ;;
    *)
        echo "Usage: $0 {count|today|stats|clean}"
        echo "  count  - Show visitor counts"
        echo "  today  - Show today's visitors"
        echo "  stats  - Show storage statistics"
        echo "  clean  - Clean temporary files"
        exit 1
        ;;
esac
EOF

chmod +x visitor-utils.sh

# Set up cron jobs
echo "Setting up cron jobs..."
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/sarawak-energy/monitor-system.sh >> /opt/sarawak-energy/shared-data/logs/health.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/sarawak-energy/backup-system.sh >> /opt/sarawak-energy/shared-data/logs/backup.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 3 * * 0 /opt/sarawak-energy/maintain-data.sh >> /opt/sarawak-energy/shared-data/logs/maintenance.log 2>&1") | crontab -

# Create README
cat > README.md << 'EOF'
# Sarawak Energy CI/CD - Master Node (File-based Storage)

## Services Running on Master Node:
- Redis Cache (Port 6379) - For session management and caching
- Jenkins Master (Port 8080) - Already running

## Storage Configuration:
- **Visitor Records**: `/opt/sarawak-energy/visitor-records/` (JSON files)
- **Visitor Images**: `/opt/sarawak-energy/visitor-images/` (JPG files by date)
- **Shared Data**: `/opt/sarawak-energy/shared-data/` (Inter-service communication)
- **Redis Data**: `/opt/sarawak-energy/redis-data/` (Cache persistence)

## Management Scripts:
- `monitor-system.sh` - Health check all services and storage
- `backup-system.sh` - Backup all file-based data
- `maintain-data.sh` - Clean old files and optimize storage
- `visitor-utils.sh` - Visitor data utilities

## Service URLs:
- Jenkins: http://18.143.157.100:8080
- Redis: 18.143.157.100:6379

## Commands:
```bash
# Check system status
./monitor-system.sh

# View visitor statistics
./visitor-utils.sh count
./visitor-utils.sh today
./visitor-utils.sh stats

# Maintenance
./maintain-data.sh
./backup-system.sh

# Service management
docker-compose -f docker-compose-master.yml logs
docker-compose -f docker-compose-master.yml restart
docker-compose -f docker-compose-master.yml down

# Clean temporary files
./visitor-utils.sh clean
```

## File Structure:
```
/opt/sarawak-energy/
├── shared-data/           # Inter-service communication
│   ├── archive/          # Processed visitor files
│   ├── logs/             # System logs
│   └── temp/             # Temporary files
├── visitor-records/       # JSON visitor records
├── visitor-images/        # JPG images by date folders
└── redis-data/           # Redis persistence
```

## Storage Benefits:
- ✅ No database installation required
- ✅ Simple file-based operations
- ✅ Easy backup and restore
- ✅ Human-readable JSON format
- ✅ Scalable directory structure
- ✅ Built-in data archival
EOF

echo ""
echo "✅ Master Node setup completed (File-based storage)!"
echo ""
echo "Services started:"
echo "- Redis Cache: localhost:6379"
echo ""
echo "Storage directories created:"
echo "- Visitor records: /opt/sarawak-energy/visitor-records/"
echo "- Visitor images: /opt/sarawak-energy/visitor-images/"
echo "- Shared data: /opt/sarawak-energy/shared-data/"
echo ""
echo "Next steps:"
echo "1. Access Jenkins at http://18.143.157.100:8080"
echo "2. Set up worker nodes"
echo "3. Configure Jenkins pipelines"
echo "4. Deploy application services"
echo ""
echo "Utility commands:"
echo "- ./monitor-system.sh     # System health check"
echo "- ./visitor-utils.sh count # Visitor statistics"
echo "- ./backup-system.sh      # Backup all data"
