#!/bin/bash
# Script to transfer codebase to GCP VM
# Run this script from your local machine (Windows/Linux/Mac)
# It will copy all necessary files to the VM

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# GCP VM Configuration
VM_IP="${VM_IP:-34.59.176.57}"  # Update with your VM's external IP
VM_USER="${VM_USER:-mukilan}"   # Update with your VM username
APP_DIR="/opt/meeting-agent"
PROJECT_DIR="Copy"  # Adjust if your project directory name is different

echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Transfer Meeting Agent Codebase to GCP VM                  ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

# Check if we're in the right directory
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}Error: Project directory '$PROJECT_DIR' not found${NC}"
    echo -e "${YELLOW}Please run this script from the directory containing the 'Copy' folder${NC}"
    exit 1
fi

echo -e "${BLUE}Configuration:${NC}"
echo -e "  ${YELLOW}VM IP:${NC} $VM_IP"
echo -e "  ${YELLOW}VM User:${NC} $VM_USER"
echo -e "  ${YELLOW}Target Directory:${NC} $APP_DIR"
echo -e "  ${YELLOW}Project Directory:${NC} $PROJECT_DIR"
echo -e ""

# Test SSH connection
echo -e "${BLUE}[1/4]${NC} ${YELLOW}Testing SSH connection...${NC}"
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no ${VM_USER}@${VM_IP} "echo 'Connection successful'" 2>/dev/null; then
    echo -e "  ${GREEN}✓ SSH connection successful${NC}"
else
    echo -e "  ${RED}✗ SSH connection failed${NC}"
    echo -e "  ${YELLOW}Please check:${NC}"
    echo -e "    - VM IP address is correct"
    echo -e "    - SSH key is configured"
    echo -e "    - GCP firewall allows SSH (port 22)"
    echo -e "    - VM is running"
    exit 1
fi

# Create target directory on VM
echo -e "${BLUE}[2/4]${NC} ${YELLOW}Creating target directory on VM...${NC}"
ssh ${VM_USER}@${VM_IP} "sudo mkdir -p $APP_DIR && sudo chown ${VM_USER}:${VM_USER} $APP_DIR" || {
    echo -e "  ${RED}✗ Failed to create directory${NC}"
    exit 1
}
echo -e "  ${GREEN}✓ Directory created${NC}"

# Create temporary archive (excluding unnecessary files)
echo -e "${BLUE}[3/4]${NC} ${YELLOW}Creating archive of application files...${NC}"
TEMP_ARCHIVE="/tmp/meeting-agent-$(date +%Y%m%d-%H%M%S).tar.gz"

# Exclude unnecessary files
tar --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='*.log' \
    --exclude='.pytest_cache' \
    --exclude='*.db' \
    --exclude='.DS_Store' \
    -czf "$TEMP_ARCHIVE" -C "$(dirname $PROJECT_DIR)" "$(basename $PROJECT_DIR)" 2>/dev/null || {
    echo -e "  ${RED}✗ Failed to create archive${NC}"
    exit 1
}

ARCHIVE_SIZE=$(du -h "$TEMP_ARCHIVE" | cut -f1)
echo -e "  ${GREEN}✓ Archive created (${ARCHIVE_SIZE})${NC}"

# Transfer archive to VM
echo -e "${BLUE}[4/4]${NC} ${YELLOW}Transferring files to VM (this may take a few minutes)...${NC}"
scp "$TEMP_ARCHIVE" ${VM_USER}@${VM_IP}:/tmp/ || {
    echo -e "  ${RED}✗ Transfer failed${NC}"
    rm -f "$TEMP_ARCHIVE"
    exit 1
}
echo -e "  ${GREEN}✓ Files transferred${NC}"

# Extract archive on VM
echo -e "${YELLOW}Extracting files on VM...${NC}"
ARCHIVE_NAME=$(basename "$TEMP_ARCHIVE")
ssh ${VM_USER}@${VM_IP} "
    cd $APP_DIR
    tar -xzf /tmp/$ARCHIVE_NAME --strip-components=1
    rm -f /tmp/$ARCHIVE_NAME
    chmod +x scripts/*.sh 2>/dev/null || true
    echo 'Files extracted successfully'
" || {
    echo -e "  ${RED}✗ Extraction failed${NC}"
    rm -f "$TEMP_ARCHIVE"
    exit 1
}

# Clean up local archive
rm -f "$TEMP_ARCHIVE"

echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Transfer Complete!                              ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}Next Steps:${NC}"
echo -e "  1. SSH into the VM: ${YELLOW}ssh ${VM_USER}@${VM_IP}${NC}"
echo -e "  2. Run the deployment script: ${YELLOW}sudo bash $APP_DIR/scripts/deploy_gcp_vm.sh${NC}"
echo -e "  3. Update the .env file: ${YELLOW}sudo nano $APP_DIR/.env${NC}"
echo -e "  4. Restart the service: ${YELLOW}sudo systemctl restart meeting-agent.service${NC}"

echo -e "\n${GREEN}✓ Files are ready on the VM for deployment!${NC}\n"

