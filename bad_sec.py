import os
import subprocess
import hashlib

# High Alert: Hardcoded secrets
AWS_SECRET_KEY = "AKIAIOSFODNN7EXAMPLE"
DB_PASSWORD = "super_secret_password_123"

def execute_system_command(cmd):
    # Security Alert: OS Command Injection
    return subprocess.call(cmd, shell=True)

def md5_hashing(password):
    # Security Alert: Weak hashing algorithm
    return hashlib.md5(password.encode()).hexdigest()
