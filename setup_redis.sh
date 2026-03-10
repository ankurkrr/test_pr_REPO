#!/bin/bash
# Redis Setup Script for Meeting Intelligence Agent
# This script helps set up Redis for both local development and VM deployment

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Redis Setup for Meeting Intelligence Agent ===${NC}\n"

# Check if running as root (for system-level installation)
if [ "$EUID" -eq 0 ]; then
    INSTALL_MODE="system"
else
    INSTALL_MODE="user"
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo -e "${RED}Cannot detect OS. Exiting.${NC}"
    exit 1
fi

echo -e "${YELLOW}Detected OS: $OS${NC}"
echo -e "${YELLOW}Install mode: $INSTALL_MODE${NC}\n"

# Function to install Redis on Ubuntu/Debian
install_redis_ubuntu() {
    echo -e "${GREEN}Installing Redis for Ubuntu/Debian...${NC}"
    
    # Update package list
    sudo apt-get update
    
    # Install Redis
    sudo apt-get install -y redis-server
    
    # Start and enable Redis service
    sudo systemctl start redis-server
    sudo systemctl enable redis-server
    
    echo -e "${GREEN}Redis installed and started successfully!${NC}"
}

# Function to install Redis on RHEL/CentOS/Fedora
install_redis_rhel() {
    echo -e "${GREEN}Installing Redis for RHEL/CentOS/Fedora...${NC}"
    
    # Install EPEL repository (for CentOS/RHEL)
    if [ "$OS" = "centos" ] || [ "$OS" = "rhel" ]; then
        sudo yum install -y epel-release
    fi
    
    # Install Redis
    if command -v dnf &> /dev/null; then
        sudo dnf install -y redis
    else
        sudo yum install -y redis
    fi
    
    # Start and enable Redis service
    sudo systemctl start redis
    sudo systemctl enable redis
    
    echo -e "${GREEN}Redis installed and started successfully!${NC}"
}

# Function to test Redis connection
test_redis() {
    echo -e "\n${YELLOW}Testing Redis connection...${NC}"
    
    if redis-cli ping | grep -q "PONG"; then
        echo -e "${GREEN}✓ Redis is running and responding!${NC}"
        
        # Display Redis info
        echo -e "\n${YELLOW}Redis Server Info:${NC}"
        redis-cli info server | head -5
        
        return 0
    else
        echo -e "${RED}✗ Redis is not responding. Please check the service status.${NC}"
        return 1
    fi
}

# Function to configure Redis for production
configure_redis() {
    echo -e "\n${YELLOW}Configuring Redis for production...${NC}"
    
    REDIS_CONF="/etc/redis/redis.conf"
    
    if [ ! -f "$REDIS_CONF" ]; then
        echo -e "${YELLOW}Redis config file not found at $REDIS_CONF${NC}"
        echo -e "${YELLOW}Skipping configuration.${NC}"
        return
    fi
    
    # Backup original config
    sudo cp "$REDIS_CONF" "${REDIS_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Update bind address to allow connections from localhost (for VM deployments)
    if ! grep -q "^bind 127.0.0.1 ::1" "$REDIS_CONF"; then
        echo -e "${GREEN}Updating bind address...${NC}"
        sudo sed -i 's/^bind .*/bind 127.0.0.1 ::1/' "$REDIS_CONF"
    fi
    
    # Set maxmemory policy (optional - uncomment if needed)
    # if ! grep -q "^maxmemory-policy" "$REDIS_CONF"; then
    #     echo "maxmemory-policy allkeys-lru" | sudo tee -a "$REDIS_CONF"
    # fi
    
    # Restart Redis to apply changes
    sudo systemctl restart redis-server 2>/dev/null || sudo systemctl restart redis
    
    echo -e "${GREEN}Redis configuration updated!${NC}"
}

# Main installation logic
main() {
    case $OS in
        ubuntu|debian)
            install_redis_ubuntu
            ;;
        centos|rhel|fedora)
            install_redis_rhel
            ;;
        *)
            echo -e "${RED}Unsupported OS: $OS${NC}"
            echo -e "${YELLOW}Please install Redis manually.${NC}"
            echo -e "${YELLOW}For most Linux distributions:${NC}"
            echo -e "  sudo apt-get install redis-server  # Ubuntu/Debian"
            echo -e "  sudo yum install redis             # RHEL/CentOS"
            echo -e "  sudo dnf install redis             # Fedora"
            exit 1
            ;;
    esac
    
    # Configure Redis
    configure_redis
    
    # Test Redis
    sleep 2
    test_redis
    
    echo -e "\n${GREEN}=== Redis Setup Complete ===${NC}"
    echo -e "\n${YELLOW}Next steps:${NC}"
    echo -e "1. Update your .env file with Redis configuration:"
    echo -e "   ${GREEN}REDIS_URL=redis://localhost:6379/0${NC}"
    echo -e "\n2. For VM deployments where Redis is on the same host:"
    echo -e "   ${GREEN}REDIS_URL=redis://localhost:6379/0${NC}"
    echo -e "\n3. For Docker deployments:"
    echo -e "   ${GREEN}REDIS_URL=redis://redis:6379/0${NC}"
    echo -e "\n4. Test the connection with:"
    echo -e "   ${GREEN}redis-cli ping${NC}"
}

# Run main function
main

