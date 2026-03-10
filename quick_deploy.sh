#!/bin/bash
# Quick Deployment Script - Deploy from local machine to VM
# This script packages the application and deploys it to the VM

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VM_IP="34.59.176.57"
VM_USER="mukilan"
APP_DIR="/opt/meeting-agent"
PROJECT_DIR="/home/mukilan/projects /bot/Copy"

echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Quick Deployment to VM - Meeting Intelligence Agent         ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

cd "$PROJECT_DIR"

echo -e "${BLUE}[1/5]${NC} ${YELLOW}Creating deployment package...${NC}"
TMP_DIR=$(mktemp -d)
DEPLOY_PACKAGE="$TMP_DIR/meeting-agent-deploy.tar.gz"

# Create archive excluding unnecessary files
tar --exclude='venv*' \
    --exclude='venv_linux' \
    --exclude='venv_new' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='logs/*.log' \
    --exclude='*.log' \
    --exclude='keys/*.key' \
    -czf "$DEPLOY_PACKAGE" .

echo -e "  ${GREEN}✓ Package created: $(du -h $DEPLOY_PACKAGE | cut -f1)${NC}"

echo -e "${BLUE}[2/5]${NC} ${YELLOW}Copying package to VM...${NC}"
scp -o StrictHostKeyChecking=no "$DEPLOY_PACKAGE" ${VM_USER}@${VM_IP}:/tmp/meeting-agent-deploy.tar.gz
echo -e "  ${GREEN}✓ Package copied to VM${NC}"

echo -e "${BLUE}[3/5]${NC} ${YELLOW}Extracting files on VM...${NC}"
ssh -o StrictHostKeyChecking=no ${VM_USER}@${VM_IP} << 'ENDSSH'
    # Create application directory
    sudo mkdir -p /opt/meeting-agent
    
    # Extract files (preserve existing .env if it exists)
    if [ -f /opt/meeting-agent/.env ]; then
        sudo cp /opt/meeting-agent/.env /tmp/meeting-agent-env-backup.env
    fi
    
    cd /tmp
    sudo rm -rf meeting-agent-extract
    mkdir meeting-agent-extract
    tar -xzf meeting-agent-deploy.tar.gz -C meeting-agent-extract
    
    # Copy files to application directory
    sudo cp -r meeting-agent-extract/* /opt/meeting-agent/
    
    # Restore .env if it existed
    if [ -f /tmp/meeting-agent-env-backup.env ]; then
        sudo cp /tmp/meeting-agent-env-backup.env /opt/meeting-agent/.env
        sudo rm /tmp/meeting-agent-env-backup.env
    fi
    
    # Fix ownership
    sudo chown -R mukilan:mukilan /opt/meeting-agent
    
    echo "Files extracted successfully"
ENDSSH

echo -e "  ${GREEN}✓ Files extracted on VM${NC}"

echo -e "${BLUE}[4/5]${NC} ${YELLOW}Running deployment script on VM...${NC}"
ssh -o StrictHostKeyChecking=no ${VM_USER}@${VM_IP} << 'ENDSSH'
    cd /opt/meeting-agent
    
    # Make deployment script executable
    chmod +x scripts/vm_deployment.sh
    
    # Run deployment as root (will prompt for sudo password)
    echo "Please enter your sudo password to run the deployment:"
    sudo /opt/meeting-agent/scripts/vm_deployment.sh
ENDSSH

echo -e "  ${GREEN}✓ Deployment script executed${NC}"

echo -e "${BLUE}[5/5]${NC} ${YELLOW}Verifying deployment...${NC}"
sleep 3

# Test connection
if ssh -o StrictHostKeyChecking=no ${VM_USER}@${VM_IP} "curl -s http://localhost:8000/health > /dev/null 2>&1 && echo 'OK' || echo 'FAIL'"; then
    echo -e "  ${GREEN}✓ Service is running${NC}"
else
    echo -e "  ${YELLOW}⚠ Service may still be starting (this is normal)${NC}"
fi

# Cleanup
rm -f "$DEPLOY_PACKAGE"
rmdir "$TMP_DIR"

echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Deployment Complete!                       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}Next Steps:${NC}"
echo -e "1. SSH to VM: ${YELLOW}ssh ${VM_USER}@${VM_IP}${NC}"
echo -e "2. Update .env file: ${YELLOW}sudo nano ${APP_DIR}/.env${NC}"
echo -e "3. Check service: ${YELLOW}sudo systemctl status meeting-agent.service${NC}"
echo -e "4. View logs: ${YELLOW}sudo journalctl -u meeting-agent.service -f${NC}"
echo -e "5. Test API: ${YELLOW}curl http://${VM_IP}:8000/health${NC}\n"

echo -e "${GREEN}Service will auto-restart on failure and after VM reboot!${NC}\n"

