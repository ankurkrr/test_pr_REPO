#!/bin/bash
# Deployment Script for Meeting Intelligence Agent VM
# This script sets up the agent for 24/7 operation on Google Cloud VM

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

VM_IP="${VM_IP:-34.59.176.57}"
VM_USER="${VM_USER:-mukilan}"
APP_DIR="${APP_DIR:-/opt/meeting-agent}"
APP_USER="${APP_USER:-meeting-agent}"

echo -e "${GREEN}=== Meeting Intelligence Agent VM Deployment ===${NC}\n"
echo -e "${YELLOW}Target VM: ${VM_USER}@${VM_IP}${NC}"
echo -e "${YELLOW}App Directory: ${APP_DIR}${NC}\n"

# Function to check if running locally or remotely
check_local() {
    if [ -z "$SSH_CONNECTION" ] && [ "$(hostname -I | grep -oE '\b34\.59\.176\.57\b')" = "" ]; then
        return 0  # Running locally
    else
        return 1  # Running on VM
    fi
}

# Function to run command on VM via SSH or locally
run_cmd() {
    if check_local; then
        echo -e "${YELLOW}Running on local machine (will deploy to VM)${NC}"
        ssh -o StrictHostKeyChecking=no ${VM_USER}@${VM_IP} "$1"
    else
        eval "$1"
    fi
}

# Function to copy files to VM
copy_to_vm() {
    if check_local; then
        echo -e "${YELLOW}Copying files to VM...${NC}"
        scp -r "$1" ${VM_USER}@${VM_IP}:"$2"
    else
        cp -r "$1" "$2"
    fi
}

echo -e "${GREEN}Step 1: Creating application directory...${NC}"
run_cmd "sudo mkdir -p ${APP_DIR} && sudo chown ${VM_USER}:${VM_USER} ${APP_DIR}"

echo -e "${GREEN}Step 2: Installing system dependencies...${NC}"
run_cmd "sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv redis-server git curl"

echo -e "${GREEN}Step 3: Setting up Redis...${NC}"
run_cmd "sudo systemctl start redis-server && sudo systemctl enable redis-server"

echo -e "${GREEN}Step 4: Creating application user (if not exists)...${NC}"
run_cmd "sudo useradd -r -s /bin/bash -d ${APP_DIR} ${APP_USER} 2>/dev/null || true"
run_cmd "sudo chown -R ${APP_USER}:${APP_USER} ${APP_DIR}"

echo -e "${GREEN}Step 5: Copying application files...${NC}"
# Note: This assumes you're running from the project root
# If running from local machine, uncomment:
# tar --exclude='venv*' --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' -czf /tmp/meeting-agent.tar.gz .
# scp /tmp/meeting-agent.tar.gz ${VM_USER}@${VM_IP}:/tmp/
# run_cmd "cd ${APP_DIR} && tar -xzf /tmp/meeting-agent.tar.gz && rm /tmp/meeting-agent.tar.gz"

echo -e "${GREEN}Step 6: Setting up Python virtual environment...${NC}"
run_cmd "cd ${APP_DIR} && python3 -m venv venv && source venv/bin/activate && pip install --upgrade pip"

echo -e "${GREEN}Step 7: Installing Python dependencies...${NC}"
run_cmd "cd ${APP_DIR} && source venv/bin/activate && pip install -r requirements.txt"

echo -e "${GREEN}Step 8: Setting up environment file...${NC}"
run_cmd "cd ${APP_DIR} && if [ ! -f .env ]; then cp env_template.txt .env && echo 'Please update .env with your configuration'; fi"

echo -e "${GREEN}Step 9: Creating log directory...${NC}"
run_cmd "sudo mkdir -p ${APP_DIR}/logs && sudo chown ${APP_USER}:${APP_USER} ${APP_DIR}/logs"

echo -e "${GREEN}Step 10: Setting up systemd service...${NC}"
run_cmd "sudo tee /etc/systemd/system/meeting-agent.service > /dev/null << 'EOFSERVICE'
[Unit]
Description=Meeting Intelligence Agent API Server
After=network.target redis.service mysql.service
Requires=redis.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=\"PATH=${APP_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin\"
Environment=\"PYTHONPATH=${APP_DIR}\"
Environment=\"APP_ENV=production\"
Environment=\"APP_ENVIRONMENT=production\"
ExecStart=${APP_DIR}/venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info
Restart=always
RestartSec=10
StandardOutput=append:${APP_DIR}/logs/app.log
StandardError=append:${APP_DIR}/logs/app.log

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096

# Security
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${APP_DIR}

[Install]
WantedBy=multi-user.target
EOFSERVICE
"

echo -e "${GREEN}Step 11: Reloading systemd and enabling service...${NC}"
run_cmd "sudo systemctl daemon-reload && sudo systemctl enable meeting-agent.service"

echo -e "${GREEN}Step 12: Starting the service...${NC}"
run_cmd "sudo systemctl start meeting-agent.service"

echo -e "${GREEN}Step 13: Checking service status...${NC}"
sleep 5
run_cmd "sudo systemctl status meeting-agent.service --no-pager -l"

echo -e "\n${GREEN}=== Deployment Complete ===${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo -e "1. Update .env file: ${APP_DIR}/.env"
echo -e "2. Restart service: sudo systemctl restart meeting-agent.service"
echo -e "3. Check logs: sudo journalctl -u meeting-agent.service -f"
echo -e "4. Check application logs: tail -f ${APP_DIR}/logs/app.log"
echo -e "\n${GREEN}Service will auto-restart on failure or reboot!${NC}"

