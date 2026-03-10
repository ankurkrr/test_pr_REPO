#!/bin/bash
# Complete VM Deployment Script for Meeting Intelligence Agent
# Run this script ON THE VM to set up everything for 24/7 operation

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
echo -e "${GREEN}║   Meeting Intelligence Agent - VM Deployment Script          ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root or with sudo${NC}"
    exit 1
fi

# Step 1: Update system
echo -e "${BLUE}[1/12]${NC} ${YELLOW}Updating system packages...${NC}"
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv redis-server git curl wget ufw nginx supervisor 2>/dev/null || \
apt-get install -y python3 python3-pip python3-venv redis-server git curl wget ufw

# Step 2: Create application user
echo -e "${BLUE}[2/12]${NC} ${YELLOW}Creating application user...${NC}"
if id "$APP_USER" &>/dev/null; then
    echo -e "  ${GREEN}✓ User $APP_USER already exists${NC}"
else
    useradd -r -s /bin/bash -d $APP_DIR -m $APP_USER
    echo -e "  ${GREEN}✓ User $APP_USER created${NC}"
fi

# Step 3: Create application directory
echo -e "${BLUE}[3/12]${NC} ${YELLOW}Setting up application directory...${NC}"
mkdir -p $APP_DIR
mkdir -p $APP_DIR/logs
mkdir -p $APP_DIR/keys
chown -R $APP_USER:$APP_USER $APP_DIR
echo -e "  ${GREEN}✓ Directory $APP_DIR created${NC}"

# Step 4: Setup Redis
echo -e "${BLUE}[4/12]${NC} ${YELLOW}Configuring Redis...${NC}"
systemctl start redis-server || service redis-server start
systemctl enable redis-server || update-rc.d redis-server enable

# Configure Redis for production
REDIS_CONF="/etc/redis/redis.conf"
if [ -f "$REDIS_CONF" ]; then
    # Backup original
    cp $REDIS_CONF ${REDIS_CONF}.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
    
    # Set bind to localhost for security
    sed -i 's/^bind .*/bind 127.0.0.1 ::1/' $REDIS_CONF 2>/dev/null || true
    
    # Set maxmemory policy
    if ! grep -q "^maxmemory-policy" $REDIS_CONF; then
        echo "maxmemory-policy allkeys-lru" >> $REDIS_CONF
    fi
fi

systemctl restart redis-server || service redis-server restart
sleep 2

# Test Redis
if redis-cli ping | grep -q "PONG"; then
    echo -e "  ${GREEN}✓ Redis is running${NC}"
else
    echo -e "  ${RED}✗ Redis failed to start${NC}"
    exit 1
fi

# Step 5: Copy application files
echo -e "${BLUE}[5/12]${NC} ${YELLOW}Copying application files...${NC}"
# Note: Files should already be in $APP_DIR if deploying from local
# Or use git clone, rsync, etc.
if [ -f "$APP_DIR/requirements.txt" ]; then
    echo -e "  ${GREEN}✓ Application files found${NC}"
else
    echo -e "  ${RED}✗ Application files not found in $APP_DIR${NC}"
    echo -e "  ${YELLOW}Please copy application files to $APP_DIR first${NC}"
    exit 1
fi

# Step 6: Setup Python virtual environment
echo -e "${BLUE}[6/12]${NC} ${YELLOW}Creating Python virtual environment...${NC}"
if [ ! -d "$APP_DIR/venv" ]; then
    sudo -u $APP_USER python3 -m venv $APP_DIR/venv
    echo -e "  ${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "  ${GREEN}✓ Virtual environment already exists${NC}"
fi

# Step 7: Install Python dependencies
echo -e "${BLUE}[7/12]${NC} ${YELLOW}Installing Python dependencies...${NC}"
sudo -u $APP_USER $APP_DIR/venv/bin/pip install --upgrade pip --quiet
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt --quiet
echo -e "  ${GREEN}✓ Dependencies installed${NC}"

# Step 8: Setup environment file
echo -e "${BLUE}[8/12]${NC} ${YELLOW}Setting up environment configuration...${NC}"
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/env_template.txt" ]; then
        sudo -u $APP_USER cp $APP_DIR/env_template.txt $APP_DIR/.env
        echo -e "  ${GREEN}✓ .env file created from template${NC}"
        echo -e "  ${YELLOW}⚠ Please update $APP_DIR/.env with your configuration${NC}"
    else
        echo -e "  ${RED}✗ env_template.txt not found${NC}"
    fi
else
    echo -e "  ${GREEN}✓ .env file already exists${NC}"
fi

# Ensure Redis URL is set in .env
if [ -f "$APP_DIR/.env" ]; then
    if ! grep -q "^REDIS_URL" $APP_DIR/.env; then
        echo "REDIS_URL=redis://localhost:6379/0" >> $APP_DIR/.env
    fi
fi

# Step 9: Create systemd service
echo -e "${BLUE}[9/12]${NC} ${YELLOW}Creating systemd service...${NC}"
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

ExecStart=/opt/meeting-agent/venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info

Restart=always
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

StandardOutput=append:/opt/meeting-agent/logs/app.log
StandardError=append:/opt/meeting-agent/logs/app.log
SyslogIdentifier=meeting-agent

LimitNOFILE=65536
LimitNPROC=4096
MemoryMax=2G

TimeoutStartSec=60
TimeoutStopSec=30

PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/opt/meeting-agent/logs /opt/meeting-agent/.env
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictRealtime=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOFSERVICE

echo -e "  ${GREEN}✓ Systemd service created${NC}"

# Step 10: Setup log rotation
echo -e "${BLUE}[10/12]${NC} ${YELLOW}Setting up log rotation...${NC}"
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

# Step 11: Reload systemd and enable service
echo -e "${BLUE}[11/12]${NC} ${YELLOW}Enabling systemd service...${NC}"
systemctl daemon-reload
systemctl enable meeting-agent.service
echo -e "  ${GREEN}✓ Service enabled${NC}"

# Step 12: Start the service
echo -e "${BLUE}[12/12]${NC} ${YELLOW}Starting service...${NC}"
systemctl start meeting-agent.service
sleep 5

# Check service status
if systemctl is-active --quiet meeting-agent.service; then
    echo -e "  ${GREEN}✓ Service is running${NC}"
else
    echo -e "  ${RED}✗ Service failed to start${NC}"
    echo -e "  ${YELLOW}Checking logs...${NC}"
    journalctl -u meeting-agent.service -n 50 --no-pager
    exit 1
fi

# Final status check
echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Deployment Complete!                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}Service Status:${NC}"
systemctl status meeting-agent.service --no-pager -l | head -20

echo -e "\n${BLUE}Health Check:${NC}"
sleep 2
if curl -s http://localhost:$APP_PORT/health > /dev/null; then
    echo -e "  ${GREEN}✓ API is responding${NC}"
else
    echo -e "  ${YELLOW}⚠ API not responding yet (may take a few seconds)${NC}"
fi

echo -e "\n${BLUE}Useful Commands:${NC}"
echo -e "  ${YELLOW}View logs:${NC}         sudo journalctl -u meeting-agent.service -f"
echo -e "  ${YELLOW}Restart:${NC}           sudo systemctl restart meeting-agent.service"
echo -e "  ${YELLOW}Status:${NC}            sudo systemctl status meeting-agent.service"
echo -e "  ${YELLOW}Stop:${NC}              sudo systemctl stop meeting-agent.service"
echo -e "  ${YELLOW}Check logs:${NC}        tail -f /opt/meeting-agent/logs/app.log"
echo -e "  ${YELLOW}Test API:${NC}         curl http://localhost:$APP_PORT/health"

echo -e "\n${GREEN}✓ Service is configured for 24/7 operation with auto-restart!${NC}\n"

