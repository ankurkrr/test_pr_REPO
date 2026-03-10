# Deployment Scripts

This directory contains scripts for deploying the Meeting Intelligence Agent to a GCP VM.

## Scripts

### 1. `transfer_to_vm.sh`
**Purpose**: Transfer codebase from local machine to GCP VM

**Usage**:
```bash
# Edit script to set VM_IP and VM_USER
nano transfer_to_vm.sh

# Run from local machine
bash transfer_to_vm.sh
```

**What it does**:
- Creates a compressed archive of the codebase
- Excludes unnecessary files (venv, __pycache__, .git, etc.)
- Transfers archive to VM via SCP
- Extracts files on VM

### 2. `deploy_gcp_vm.sh`
**Purpose**: Complete deployment setup on GCP VM

**Usage**:
```bash
# SSH into VM first
ssh your-user@VM_IP

# Run on VM (requires sudo)
sudo bash /opt/meeting-agent/scripts/deploy_gcp_vm.sh
```

**What it does**:
- Updates system packages
- Installs Python 3, Redis, and dependencies
- Creates application user (`meeting-agent`)
- Sets up Python virtual environment
- Installs Python dependencies
- Configures Redis
- Creates systemd service for 24/7 operation
- Sets up log rotation
- Configures firewall (basic)
- Starts the service

## Deployment Flow

```
Local Machine                    GCP VM
     |                              |
     |--[1. transfer_to_vm.sh]----->|
     |                              |--[2. deploy_gcp_vm.sh]-->
     |                              |   (Install & Configure)
     |                              |
     |<--[3. SSH & Configure]-------|
     |   (Update .env file)         |
     |                              |
     |<--[4. Verify]----------------|
     |   (Test API)                 |
```

## Prerequisites

### Local Machine
- SSH access to GCP VM
- `tar`, `scp` commands available
- Codebase in `Copy/` directory

### GCP VM
- Debian 12 (Bookworm) or compatible
- Root/sudo access
- Internet connection for package installation
- At least 2GB free disk space

## Configuration

### Before Transfer
Edit `transfer_to_vm.sh`:
```bash
VM_IP="34.59.176.57"      # Your VM's external IP
VM_USER="mukilan"         # Your VM username
```

### After Deployment
Update `/opt/meeting-agent/.env` with production configuration:
- Database credentials
- Security keys
- API keys
- Google Cloud credentials

## Troubleshooting

### Transfer Fails
- Check SSH connection: `ssh your-user@VM_IP`
- Verify VM is running
- Check GCP firewall allows SSH (port 22)
- Verify SSH key is configured

### Deployment Fails
- Check logs: `journalctl -u meeting-agent.service -n 100`
- Verify all dependencies installed
- Check disk space: `df -h`
- Verify Python version: `python3 --version`

### Service Won't Start
- Check environment variables: `cat /opt/meeting-agent/.env`
- Verify Redis is running: `redis-cli ping`
- Check file permissions: `ls -la /opt/meeting-agent`
- View logs: `journalctl -u meeting-agent.service -f`

## Manual Deployment

If scripts fail, you can deploy manually:

1. **Transfer files manually**:
   ```bash
   tar -czf meeting-agent.tar.gz Copy/
   scp meeting-agent.tar.gz user@VM_IP:/tmp/
   ssh user@VM_IP
   sudo mkdir -p /opt/meeting-agent
   sudo tar -xzf /tmp/meeting-agent.tar.gz -C /opt/meeting-agent
   ```

2. **Install dependencies**:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip python3-venv redis-server
   ```

3. **Setup Python environment**:
   ```bash
   sudo useradd -r -s /bin/bash -d /opt/meeting-agent meeting-agent
   sudo -u meeting-agent python3 -m venv /opt/meeting-agent/venv
   sudo -u meeting-agent /opt/meeting-agent/venv/bin/pip install -r /opt/meeting-agent/requirements.txt
   ```

4. **Configure systemd**:
   ```bash
   sudo cp /opt/meeting-agent/systemd/meeting-agent.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable meeting-agent.service
   sudo systemctl start meeting-agent.service
   ```

## Security Notes

- Scripts use `sudo` for system-level operations
- Application runs as non-root user (`meeting-agent`)
- `.env` file should have restricted permissions (640)
- Firewall rules should be configured in GCP Console

## Support

For detailed deployment instructions, see:
- `../docs/GCP_VM_DEPLOYMENT_GUIDE.md` - Complete deployment guide
- `../DEPLOYMENT_QUICK_START.md` - Quick start guide

