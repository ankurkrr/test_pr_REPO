#!/bin/bash
# Automated GCP VM Deployment using gcloud CLI
# This script deploys the Meeting Intelligence Agent to GCP VM using gcloud commands
# Run this script from your local machine

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# GCP Configuration
PROJECT_ID="${GCP_PROJECT_ID:-}"  # Set via environment variable or edit here
INSTANCE_NAME="${GCP_INSTANCE_NAME:-meeting-agent-vm}"
ZONE="${GCP_ZONE:-us-central1-a}"
APP_DIR="/opt/meeting-agent"
PROJECT_DIR="Copy"  # Adjust if your project directory name is different

echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Automated GCP VM Deployment using gcloud CLI              ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed${NC}"
    echo -e "${YELLOW}Please install gcloud CLI: https://cloud.google.com/sdk/docs/install${NC}"
    exit 1
fi

# Check if we're authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo -e "${YELLOW}Please run: gcloud auth login${NC}"
    exit 1
fi

# Get project ID if not set
if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
    if [ -z "$PROJECT_ID" ]; then
        echo -e "${RED}Error: GCP_PROJECT_ID not set and no default project configured${NC}"
        echo -e "${YELLOW}Please set GCP_PROJECT_ID environment variable or run: gcloud config set project YOUR_PROJECT_ID${NC}"
        exit 1
    fi
fi

echo -e "${BLUE}Configuration:${NC}"
echo -e "  ${YELLOW}Project ID:${NC} $PROJECT_ID"
echo -e "  ${YELLOW}Instance:${NC} $INSTANCE_NAME"
echo -e "  ${YELLOW}Zone:${NC} $ZONE"
echo -e "  ${YELLOW}Target Directory:${NC} $APP_DIR"
echo -e ""

# Verify instance exists
echo -e "${BLUE}[1/8]${NC} ${YELLOW}Verifying VM instance...${NC}"
if ! gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" &>/dev/null; then
    echo -e "  ${RED}✗ Instance '$INSTANCE_NAME' not found in zone '$ZONE'${NC}"
    echo -e "  ${YELLOW}Please check the instance name and zone${NC}"
    exit 1
fi

# Check instance status
INSTANCE_STATUS=$(gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --format="value(status)")
if [ "$INSTANCE_STATUS" != "RUNNING" ]; then
    echo -e "  ${YELLOW}Instance is not running (status: $INSTANCE_STATUS). Starting instance...${NC}"
    gcloud compute instances start "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID"
    echo -e "  ${YELLOW}Waiting for instance to be ready...${NC}"
    sleep 10
fi

echo -e "  ${GREEN}✓ Instance is running${NC}"

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}Error: Project directory '$PROJECT_DIR' not found${NC}"
    echo -e "${YELLOW}Please run this script from the directory containing the 'Copy' folder${NC}"
    exit 1
fi

# Step 1: Create temporary archive
echo -e "${BLUE}[2/8]${NC} ${YELLOW}Creating archive of application files...${NC}"
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
    --exclude='*.swp' \
    --exclude='*.swo' \
    -czf "$TEMP_ARCHIVE" -C "$(dirname $PROJECT_DIR)" "$(basename $PROJECT_DIR)" 2>/dev/null || {
    echo -e "  ${RED}✗ Failed to create archive${NC}"
    exit 1
}

ARCHIVE_SIZE=$(du -h "$TEMP_ARCHIVE" | cut -f1)
echo -e "  ${GREEN}✓ Archive created (${ARCHIVE_SIZE})${NC}"

# Step 2: Transfer archive to VM
echo -e "${BLUE}[3/8]${NC} ${YELLOW}Transferring files to VM (this may take a few minutes)...${NC}"
gcloud compute scp "$TEMP_ARCHIVE" "$INSTANCE_NAME:/tmp/" --zone="$ZONE" --project="$PROJECT_ID" || {
    echo -e "  ${RED}✗ Transfer failed${NC}"
    rm -f "$TEMP_ARCHIVE"
    exit 1
}
echo -e "  ${GREEN}✓ Files transferred${NC}"

# Step 3: Create application directory on VM
echo -e "${BLUE}[4/8]${NC} ${YELLOW}Setting up application directory on VM...${NC}"
ARCHIVE_NAME=$(basename "$TEMP_ARCHIVE")
gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
    sudo mkdir -p $APP_DIR
    sudo chmod 755 $APP_DIR
    cd $APP_DIR
    sudo tar -xzf /tmp/$ARCHIVE_NAME --strip-components=1
    sudo rm -f /tmp/$ARCHIVE_NAME
    sudo chmod +x scripts/*.sh 2>/dev/null || true
    echo 'Files extracted successfully'
" || {
    echo -e "  ${RED}✗ Failed to extract files${NC}"
    rm -f "$TEMP_ARCHIVE"
    exit 1
}

# Clean up local archive
rm -f "$TEMP_ARCHIVE"
echo -e "  ${GREEN}✓ Files extracted on VM${NC}"

# Step 4: Run deployment script on VM
echo -e "${BLUE}[5/8]${NC} ${YELLOW}Running deployment script on VM...${NC}"
echo -e "  ${YELLOW}This will install dependencies and configure the service (may take 5-10 minutes)...${NC}"

# Run deployment script with output streaming
gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
    cd $APP_DIR
    sudo bash scripts/deploy_gcp_vm.sh
" || {
    echo -e "  ${RED}✗ Deployment failed${NC}"
    echo -e "  ${YELLOW}Check logs on VM for details${NC}"
    exit 1
}

echo -e "  ${GREEN}✓ Deployment completed${NC}"

# Step 5: Verify service status
echo -e "${BLUE}[6/8]${NC} ${YELLOW}Verifying service status...${NC}"
sleep 5

SERVICE_STATUS=$(gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
    systemctl is-active meeting-agent.service 2>/dev/null || echo 'inactive'
" --quiet 2>/dev/null | tr -d '\r\n')

if [ "$SERVICE_STATUS" = "active" ]; then
    echo -e "  ${GREEN}✓ Service is running${NC}"
else
    echo -e "  ${YELLOW}⚠ Service status: $SERVICE_STATUS${NC}"
    echo -e "  ${YELLOW}Service may need configuration. Check logs on VM.${NC}"
fi

# Step 6: Check API health
echo -e "${BLUE}[7/8]${NC} ${YELLOW}Checking API health...${NC}"
sleep 3

HEALTH_CHECK=$(gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
    curl -s http://localhost:8000/health 2>/dev/null || echo 'not_responding'
" --quiet 2>/dev/null | tr -d '\r\n')

if [ "$HEALTH_CHECK" != "not_responding" ] && [ -n "$HEALTH_CHECK" ]; then
    echo -e "  ${GREEN}✓ API is responding${NC}"
else
    echo -e "  ${YELLOW}⚠ API not responding yet (may need .env configuration)${NC}"
fi

# Step 7: Get VM external IP
echo -e "${BLUE}[8/8]${NC} ${YELLOW}Getting VM connection details...${NC}"
EXTERNAL_IP=$(gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null || echo "")

# Final summary
echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Deployment Complete!                             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}Deployment Summary:${NC}"
echo -e "  ${YELLOW}Instance:${NC} $INSTANCE_NAME"
echo -e "  ${YELLOW}Zone:${NC} $ZONE"
if [ -n "$EXTERNAL_IP" ]; then
    echo -e "  ${YELLOW}External IP:${NC} $EXTERNAL_IP"
fi
echo -e "  ${YELLOW}Service Status:${NC} $SERVICE_STATUS"
echo -e "  ${YELLOW}Application Directory:${NC} $APP_DIR"

echo -e "\n${BLUE}Next Steps:${NC}"
echo -e "  1. ${YELLOW}SSH into VM:${NC} gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo -e "  2. ${YELLOW}Configure .env file:${NC} sudo nano $APP_DIR/.env"
echo -e "  3. ${YELLOW}Restart service:${NC} sudo systemctl restart meeting-agent.service"
echo -e "  4. ${YELLOW}Check logs:${NC} sudo journalctl -u meeting-agent.service -f"

echo -e "\n${BLUE}Useful Commands:${NC}"
echo -e "  ${YELLOW}SSH to VM:${NC} gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo -e "  ${YELLOW}View service status:${NC} gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo systemctl status meeting-agent.service'"
echo -e "  ${YELLOW}View logs:${NC} gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo journalctl -u meeting-agent.service -n 50'"

if [ -n "$EXTERNAL_IP" ]; then
    echo -e "\n${BLUE}API Access:${NC}"
    echo -e "  ${YELLOW}Local (from VM):${NC} curl http://localhost:8000/health"
    echo -e "  ${YELLOW}External (if firewall allows):${NC} curl http://$EXTERNAL_IP:8000/health"
    echo -e "  ${YELLOW}Note:${NC} Ensure GCP firewall allows port 8000 for external access"
fi

echo -e "\n${GREEN}✓ Deployment completed successfully!${NC}\n"
echo -e "${YELLOW}⚠ Remember to configure the .env file with your production values!${NC}\n"

