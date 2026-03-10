#!/bin/bash
# Complete GCP VM Deployment Script for Meeting Intelligence Agent
# This script sets up everything needed for 24/7 operation on GCP VM
# Run this script ON THE VM (meeting-agent-vm) as root or with sudo

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

APP_DIR="/opt/meeting-agent"
APP_USER="meeting-agent"
APP_PORT=8000
CURRENT_USER=$(whoami)

echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Meeting Intelligence Agent - GCP VM Deployment            ║${NC}"
echo -e "${GREEN}║   VM: meeting-agent-vm (us-central1-a)                      ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root or with sudo${NC}"
    echo -e "${YELLOW}Usage: sudo bash deploy_gcp_vm.sh${NC}"
    exit 1
fi

# Step 1: Update system packages
echo -e "${BLUE}[1/15]${NC} ${YELLOW}Updating system packages...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y python3 python3-pip python3-venv python3-dev \
    redis-server git curl wget build-essential \
    libssl-dev libffi-dev libmysqlclient-dev pkg-config \
    ufw nginx supervisor logrotate 2>/dev/null || \
apt-get install -y python3 python3-pip python3-venv python3-dev \
    redis-server git curl wget build-essential \
    libssl-dev libffi-dev pkg-config
echo -e "  ${GREEN}✓ System packages updated${NC}"

# Step 2: Create application user
echo -e "${BLUE}[2/15]${NC} ${YELLOW}Creating application user...${NC}"
if id "$APP_USER" &>/dev/null; then
    echo -e "  ${GREEN}✓ User $APP_USER already exists${NC}"
else
    useradd -r -s /bin/bash -d $APP_DIR -m $APP_USER
    echo -e "  ${GREEN}✓ User $APP_USER created${NC}"
fi

# Step 3: Create application directory structure
echo -e "${BLUE}[3/15]${NC} ${YELLOW}Setting up application directory...${NC}"
mkdir -p $APP_DIR
mkdir -p $APP_DIR/logs
mkdir -p $APP_DIR/keys
mkdir -p $APP_DIR/prompts
mkdir -p $APP_DIR/client
chown -R $APP_USER:$APP_USER $APP_DIR
echo -e "  ${GREEN}✓ Directory structure created${NC}"

# Step 4: Setup Redis
echo -e "${BLUE}[4/15]${NC} ${YELLOW}Configuring Redis...${NC}"
systemctl stop redis-server 2>/dev/null || true
systemctl start redis-server || service redis-server start
systemctl enable redis-server || update-rc.d redis-server enable

# Configure Redis for production
REDIS_CONF="/etc/redis/redis.conf"
if [ -f "$REDIS_CONF" ]; then
    # Backup original
    cp $REDIS_CONF ${REDIS_CONF}.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
    
    # Set bind to localhost for security
    if ! grep -q "^bind 127.0.0.1" $REDIS_CONF; then
        sed -i 's/^# bind 127.0.0.1/bind 127.0.0.1 ::1/' $REDIS_CONF 2>/dev/null || \
        sed -i 's/^bind .*/bind 127.0.0.1 ::1/' $REDIS_CONF 2>/dev/null || \
        echo "bind 127.0.0.1 ::1" >> $REDIS_CONF
    fi
    
    # Set maxmemory policy (for 4GB VM, use 512MB for Redis)
    if ! grep -q "^maxmemory" $REDIS_CONF; then
        echo "maxmemory 512mb" >> $REDIS_CONF
    fi
    if ! grep -q "^maxmemory-policy" $REDIS_CONF; then
        echo "maxmemory-policy allkeys-lru" >> $REDIS_CONF
    fi
    
    # Disable protected mode for localhost only
    sed -i 's/^protected-mode yes/protected-mode no/' $REDIS_CONF 2>/dev/null || true
fi

systemctl restart redis-server || service redis-server restart
sleep 3

# Test Redis
if redis-cli ping | grep -q "PONG"; then
    echo -e "  ${GREEN}✓ Redis is running${NC}"
else
    echo -e "  ${RED}✗ Redis failed to start${NC}"
    exit 1
fi

# Step 5: Verify application files exist
echo -e "${BLUE}[5/15]${NC} ${YELLOW}Verifying application files...${NC}"
if [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo -e "  ${RED}✗ Application files not found in $APP_DIR${NC}"
    echo -e "  ${YELLOW}Please copy application files to $APP_DIR first${NC}"
    echo -e "  ${YELLOW}You can use the transfer script or manually copy files${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓ Application files found${NC}"

# Step 6: Setup Python virtual environment
echo -e "${BLUE}[6/15]${NC} ${YELLOW}Creating Python virtual environment...${NC}"
if [ ! -d "$APP_DIR/venv" ]; then
    sudo -u $APP_USER python3 -m venv $APP_DIR/venv
    echo -e "  ${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "  ${YELLOW}Virtual environment already exists, recreating...${NC}"
    rm -rf $APP_DIR/venv
    sudo -u $APP_USER python3 -m venv $APP_DIR/venv
    echo -e "  ${GREEN}✓ Virtual environment recreated${NC}"
fi

# Step 7: Upgrade pip and install dependencies
echo -e "${BLUE}[7/15]${NC} ${YELLOW}Installing Python dependencies (this may take a few minutes)...${NC}"
sudo -u $APP_USER $APP_DIR/venv/bin/pip install --upgrade pip setuptools wheel --quiet
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt --quiet
echo -e "  ${GREEN}✓ Dependencies installed${NC}"

# Step 8: Setup environment file
echo -e "${BLUE}[8/15]${NC} ${YELLOW}Setting up environment configuration...${NC}"
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/env_template.txt" ]; then
        sudo -u $APP_USER cp $APP_DIR/env_template.txt $APP_DIR/.env
        echo -e "  ${GREEN}✓ .env file created from template${NC}"
        echo -e "  ${YELLOW}⚠ IMPORTANT: Update $APP_DIR/.env with your production configuration${NC}"
    else
        echo -e "  ${RED}✗ env_template.txt not found${NC}"
        echo -e "  ${YELLOW}Creating minimal .env file...${NC}"
        sudo -u $APP_USER touch $APP_DIR/.env
        echo "APP_ENVIRONMENT=production" | sudo -u $APP_USER tee -a $APP_DIR/.env > /dev/null
    fi
else
    echo -e "  ${GREEN}✓ .env file already exists${NC}"
fi

# Ensure Redis URL is set in .env
if [ -f "$APP_DIR/.env" ]; then
    if ! grep -q "^REDIS_URL" $APP_DIR/.env; then
        echo "REDIS_URL=redis://localhost:6379/0" | sudo -u $APP_USER tee -a $APP_DIR/.env > /dev/null
    fi
    if ! grep -q "^APP_ENVIRONMENT" $APP_DIR/.env; then
        echo "APP_ENVIRONMENT=production" | sudo -u $APP_USER tee -a $APP_DIR/.env > /dev/null
    fi
fi

# Step 9: Set proper permissions
echo -e "${BLUE}[9/15]${NC} ${YELLOW}Setting file permissions...${NC}"
chown -R $APP_USER:$APP_USER $APP_DIR
chmod 750 $APP_DIR
chmod 640 $APP_DIR/.env 2>/dev/null || true
chmod 755 $APP_DIR/logs
echo -e "  ${GREEN}✓ Permissions set${NC}"

# Step 10: Create systemd service
echo -e "${BLUE}[10/15]${NC} ${YELLOW}Creating systemd service for 24/7 operation...${NC}"
cat > /etc/systemd/system/meeting-agent.service << 'EOFSERVICE'
[Unit]
Description=Meeting Intelligence Agent API Server
Documentation=https://github.com/your-repo/meeting-agent
After=network.target redis.service mysql.service
Requires=redis.service
Wants=network-online.target

[Service]
Type=simple
User=meeting-agent
Group=meeting-agent
WorkingDirectory=/opt/meeting-agent
Environment="PATH=/opt/meeting-agent/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=/opt/meeting-agent"
Environment="APP_ENV=production"
Environment="APP_ENVIRONMENT=production"
Environment="REDIS_URL=redis://localhost:6379/0"

# Start command
ExecStart=/opt/meeting-agent/venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info

# Auto-restart configuration for 24/7 operation
Restart=always
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

# Logging
StandardOutput=append:/opt/meeting-agent/logs/app.log
StandardError=append:/opt/meeting-agent/logs/app.log
SyslogIdentifier=meeting-agent

# Resource limits (optimized for e2-medium: 2 vCPUs, 4GB RAM)
LimitNOFILE=65536
LimitNPROC=4096
MemoryMax=2G
CPUQuota=200%

# Health check
TimeoutStartSec=60
TimeoutStopSec=30

# Security hardening
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/opt/meeting-agent/logs /opt/meeting-agent/.env /opt/meeting-agent/keys
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictRealtime=yes
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

# Kill configuration
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOFSERVICE

echo -e "  ${GREEN}✓ Systemd service created${NC}"

# Step 11: Setup log rotation
echo -e "${BLUE}[11/15]${NC} ${YELLOW}Setting up log rotation...${NC}"
cat > /etc/logrotate.d/meeting-agent << 'EOFLOGROTATE'
/opt/meeting-agent/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 meeting-agent meeting-agent
    sharedscripts
    postrotate
        systemctl reload meeting-agent > /dev/null 2>&1 || true
    endscript
}
EOFLOGROTATE

echo -e "  ${GREEN}✓ Log rotation configured${NC}"

# Step 12: Configure firewall (optional - basic setup)
echo -e "${BLUE}[12/15]${NC} ${YELLOW}Configuring firewall...${NC}"
if command -v ufw &> /dev/null; then
    ufw --force enable 2>/dev/null || true
    ufw allow 22/tcp 2>/dev/null || true  # SSH
    ufw allow 8000/tcp 2>/dev/null || true  # Application port
    echo -e "  ${GREEN}✓ Firewall configured${NC}"
    echo -e "  ${YELLOW}⚠ Note: Ensure GCP firewall rules allow port 8000${NC}"
else
    echo -e "  ${YELLOW}⚠ UFW not available, skipping firewall setup${NC}"
fi

# Step 13: Reload systemd and enable service
echo -e "${BLUE}[13/15]${NC} ${YELLOW}Enabling systemd service...${NC}"
systemctl daemon-reload
systemctl enable meeting-agent.service
echo -e "  ${GREEN}✓ Service enabled for auto-start on boot${NC}"

# Step 14: Start the service
echo -e "${BLUE}[14/15]${NC} ${YELLOW}Starting service...${NC}"
systemctl start meeting-agent.service
sleep 5

# Check service status
if systemctl is-active --quiet meeting-agent.service; then
    echo -e "  ${GREEN}✓ Service is running${NC}"
else
    echo -e "  ${RED}✗ Service failed to start${NC}"
    echo -e "  ${YELLOW}Checking logs...${NC}"
    journalctl -u meeting-agent.service -n 50 --no-pager || true
    echo -e "  ${YELLOW}Please check the logs and configuration${NC}"
    exit 1
fi

# Step 15: Final verification
echo -e "${BLUE}[15/15]${NC} ${YELLOW}Verifying deployment...${NC}"
sleep 3

# Check if API is responding
if curl -s http://localhost:$APP_PORT/health > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ API is responding${NC}"
else
    echo -e "  ${YELLOW}⚠ API not responding yet (may take a few more seconds)${NC}"
fi

# Final status check
echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Deployment Complete!                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}Service Status:${NC}"
systemctl status meeting-agent.service --no-pager -l | head -15

echo -e "\n${BLUE}Useful Commands:${NC}"
echo -e "  ${YELLOW}View service logs:${NC}     sudo journalctl -u meeting-agent.service -f"
echo -e "  ${YELLOW}View app logs:${NC}         tail -f /opt/meeting-agent/logs/app.log"
echo -e "  ${YELLOW}Restart service:${NC}       sudo systemctl restart meeting-agent.service"
echo -e "  ${YELLOW}Stop service:${NC}          sudo systemctl stop meeting-agent.service"
echo -e "  ${YELLOW}Status:${NC}                sudo systemctl status meeting-agent.service"
echo -e "  ${YELLOW}Test API:${NC}             curl http://localhost:$APP_PORT/health"

echo -e "\n${BLUE}Important Notes:${NC}"
echo -e "  ${YELLOW}1.${NC} Update /opt/meeting-agent/.env with your production configuration"
echo -e "  ${YELLOW}2.${NC} Ensure all required environment variables are set (see env_template.txt)"
echo -e "  ${YELLOW}3.${NC} Configure GCP firewall rules to allow port 8000 if needed"
echo -e "  ${YELLOW}4.${NC} Service will auto-restart on failure or VM reboot"
echo -e "  ${YELLOW}5.${NC} Logs are rotated daily and kept for 14 days"

echo -e "\n${GREEN}✓ Service is configured for 24/7 operation with auto-restart!${NC}\n"

