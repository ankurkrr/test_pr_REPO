# Automated GCP VM Deployment using gcloud CLI (PowerShell)
# This script deploys the Meeting Intelligence Agent to GCP VM using gcloud commands
# Run this script from your local Windows machine

$ErrorActionPreference = "Stop"

# GCP Configuration
$PROJECT_ID = if ($env:GCP_PROJECT_ID) { $env:GCP_PROJECT_ID } else { "" }
$INSTANCE_NAME = if ($env:GCP_INSTANCE_NAME) { $env:GCP_INSTANCE_NAME } else { "meeting-agent-vm" }
$ZONE = if ($env:GCP_ZONE) { $env:GCP_ZONE } else { "us-central1-a" }
$APP_DIR = "/opt/meeting-agent"
$PROJECT_DIR = "Copy"

Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║   Automated GCP VM Deployment using gcloud CLI              ║" -ForegroundColor Green
Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

# Check if gcloud is installed
try {
    $null = gcloud version 2>&1
} catch {
    Write-Host "Error: gcloud CLI is not installed" -ForegroundColor Red
    Write-Host "Please install gcloud CLI: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
    exit 1
}

# Check if we're authenticated
$authStatus = gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>&1
if (-not $authStatus) {
    Write-Host "Error: Not authenticated with gcloud" -ForegroundColor Red
    Write-Host "Please run: gcloud auth login" -ForegroundColor Yellow
    exit 1
}

# Get project ID if not set
if (-not $PROJECT_ID) {
    $PROJECT_ID = gcloud config get-value project 2>&1
    if (-not $PROJECT_ID -or $PROJECT_ID -match "ERROR") {
        Write-Host "Error: GCP_PROJECT_ID not set and no default project configured" -ForegroundColor Red
        Write-Host "Please set GCP_PROJECT_ID environment variable or run: gcloud config set project YOUR_PROJECT_ID" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "Configuration:" -ForegroundColor Blue
Write-Host "  Project ID: $PROJECT_ID" -ForegroundColor Yellow
Write-Host "  Instance: $INSTANCE_NAME" -ForegroundColor Yellow
Write-Host "  Zone: $ZONE" -ForegroundColor Yellow
Write-Host "  Target Directory: $APP_DIR" -ForegroundColor Yellow
Write-Host ""

# Verify instance exists
Write-Host "[1/8] Verifying VM instance..." -ForegroundColor Blue
try {
    $null = gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID 2>&1
} catch {
    Write-Host "  ✗ Instance '$INSTANCE_NAME' not found in zone '$ZONE'" -ForegroundColor Red
    Write-Host "  Please check the instance name and zone" -ForegroundColor Yellow
    exit 1
}

# Check instance status
$instanceStatus = gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID --format="value(status)" 2>&1
if ($instanceStatus -ne "RUNNING") {
    Write-Host "  Instance is not running (status: $instanceStatus). Starting instance..." -ForegroundColor Yellow
    gcloud compute instances start $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID
    Write-Host "  Waiting for instance to be ready..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

Write-Host "  ✓ Instance is running" -ForegroundColor Green

# Check if project directory exists
if (-not (Test-Path $PROJECT_DIR)) {
    Write-Host "Error: Project directory '$PROJECT_DIR' not found" -ForegroundColor Red
    Write-Host "Please run this script from the directory containing the 'Copy' folder" -ForegroundColor Yellow
    exit 1
}

# Step 1: Create temporary archive
Write-Host "[2/8] Creating archive of application files..." -ForegroundColor Blue
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$TEMP_ARCHIVE = "$env:TEMP\meeting-agent-$timestamp.tar.gz"

# Create archive using tar (Windows 10+ has tar)
$excludeItems = @(
    "venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
    ".env",
    "*.log",
    ".pytest_cache",
    "*.db",
    ".DS_Store",
    "*.swp",
    "*.swo"
)

# Use 7zip or tar if available
$useTar = $false
try {
    $null = tar --version 2>&1
    $useTar = $true
} catch {
    $useTar = $false
}

if ($useTar) {
    # Use tar (Windows 10+)
    Push-Location (Split-Path $PROJECT_DIR -Parent)
    tar -czf $TEMP_ARCHIVE --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='.env' --exclude='*.log' (Split-Path $PROJECT_DIR -Leaf)
    Pop-Location
} else {
    Write-Host "  Error: tar command not available. Please install tar or use WSL." -ForegroundColor Red
    Write-Host "  Alternative: Use the bash script (deploy_with_gcloud.sh) in WSL or Linux" -ForegroundColor Yellow
    exit 1
}

$archiveSize = (Get-Item $TEMP_ARCHIVE).Length / 1MB
$archiveSizeMB = [math]::Round($archiveSize, 2)
Write-Host "  Archive created ($archiveSizeMB MB)" -ForegroundColor Green

# Step 2: Transfer archive to VM
Write-Host "[3/8] Transferring files to VM (this may take a few minutes)..." -ForegroundColor Blue
$archiveName = Split-Path $TEMP_ARCHIVE -Leaf
gcloud compute scp $TEMP_ARCHIVE "${INSTANCE_NAME}:/tmp/" --zone=$ZONE --project=$PROJECT_ID
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Transfer failed" -ForegroundColor Red
    Remove-Item $TEMP_ARCHIVE -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "  ✓ Files transferred" -ForegroundColor Green

# Step 3: Create application directory on VM
Write-Host "[4/8] Setting up application directory on VM..." -ForegroundColor Blue
$extractCommand = @"
sudo mkdir -p $APP_DIR
sudo chmod 755 $APP_DIR
cd $APP_DIR
sudo tar -xzf /tmp/$archiveName --strip-components=1
sudo rm -f /tmp/$archiveName
sudo chmod +x scripts/*.sh 2>/dev/null || true
echo 'Files extracted successfully'
"@

gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID --command=$extractCommand
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Failed to extract files" -ForegroundColor Red
    Remove-Item $TEMP_ARCHIVE -ErrorAction SilentlyContinue
    exit 1
}

Remove-Item $TEMP_ARCHIVE -ErrorAction SilentlyContinue
Write-Host "  ✓ Files extracted on VM" -ForegroundColor Green

# Step 4: Run deployment script on VM
Write-Host "[5/8] Running deployment script on VM..." -ForegroundColor Blue
Write-Host "  This will install dependencies and configure the service (may take 5-10 minutes)..." -ForegroundColor Yellow

$deployCommand = "cd $APP_DIR; sudo bash scripts/deploy_gcp_vm.sh"
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID --command=$deployCommand
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Deployment failed" -ForegroundColor Red
    Write-Host "  Check logs on VM for details" -ForegroundColor Yellow
    exit 1
}

Write-Host "  ✓ Deployment completed" -ForegroundColor Green

# Step 5: Verify service status
Write-Host "[6/8] Verifying service status..." -ForegroundColor Blue
Start-Sleep -Seconds 5

$statusCommand = "systemctl is-active meeting-agent.service 2>/dev/null || echo 'inactive'; exit 0"
$serviceStatus = gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID --command=$statusCommand --quiet 2>&1 | ForEach-Object { $_.Trim() }

if ($serviceStatus -eq "active") {
    Write-Host "  ✓ Service is running" -ForegroundColor Green
} else {
    Write-Host "  ⚠ Service status: $serviceStatus" -ForegroundColor Yellow
    Write-Host "  Service may need configuration. Check logs on VM." -ForegroundColor Yellow
}

# Step 6: Check API health
Write-Host "[7/8] Checking API health..." -ForegroundColor Blue
Start-Sleep -Seconds 3

$healthCommand = "curl -s http://localhost:8000/health 2>/dev/null; if [ `$? -ne 0 ]; then echo 'not_responding'; fi; exit 0"
$healthCheck = gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID --command=$healthCommand --quiet 2>&1 | ForEach-Object { $_.Trim() }

if ($healthCheck -ne "not_responding" -and $healthCheck) {
    Write-Host "  ✓ API is responding" -ForegroundColor Green
} else {
    Write-Host "  ⚠ API not responding yet (may need .env configuration)" -ForegroundColor Yellow
}

# Step 7: Get VM external IP
Write-Host "[8/8] Getting VM connection details..." -ForegroundColor Blue
$externalIP = gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --project=$PROJECT_ID --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>&1

# Final summary
Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║              Deployment Complete!                             ║" -ForegroundColor Green
Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

Write-Host "Deployment Summary:" -ForegroundColor Blue
Write-Host "  Instance: $INSTANCE_NAME" -ForegroundColor Yellow
Write-Host "  Zone: $ZONE" -ForegroundColor Yellow
if ($externalIP) {
    Write-Host "  External IP: $externalIP" -ForegroundColor Yellow
}
Write-Host "  Service Status: $serviceStatus" -ForegroundColor Yellow
Write-Host "  Application Directory: $APP_DIR" -ForegroundColor Yellow

Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Blue
Write-Host "  1. SSH into VM: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE" -ForegroundColor Yellow
Write-Host "  2. Configure .env file: sudo nano $APP_DIR/.env" -ForegroundColor Yellow
Write-Host "  3. Restart service: sudo systemctl restart meeting-agent.service" -ForegroundColor Yellow
Write-Host "  4. Check logs: sudo journalctl -u meeting-agent.service -f" -ForegroundColor Yellow

Write-Host ""
Write-Host "Useful Commands:" -ForegroundColor Blue
Write-Host "  SSH to VM: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE" -ForegroundColor Yellow
Write-Host "  View service status: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo systemctl status meeting-agent.service'" -ForegroundColor Yellow
Write-Host "  View logs: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo journalctl -u meeting-agent.service -n 50'" -ForegroundColor Yellow

if ($externalIP) {
    Write-Host ""
    Write-Host "API Access:" -ForegroundColor Blue
    Write-Host "  Local (from VM): curl http://localhost:8000/health" -ForegroundColor Yellow
    Write-Host "  External (if firewall allows): curl http://$externalIP:8000/health" -ForegroundColor Yellow
    Write-Host "  Note: Ensure GCP firewall allows port 8000 for external access" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✓ Deployment completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "⚠ Remember to configure the .env file with your production values!" -ForegroundColor Yellow
Write-Host ""

