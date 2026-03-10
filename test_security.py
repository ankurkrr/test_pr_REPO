# test_security.py

import subprocess
import hashlib
import os

# Hardcoded credentials
AWS_SECRET_KEY = "AKIAIOSFODNN7EXAMPLE"
DB_PASSWORD = "super_secret_password_123"


def execute_command(cmd):
    # Command injection vulnerability
    return subprocess.call(cmd, shell=True)


def weak_hash(password):
    # Weak hashing algorithm
    return hashlib.md5(password.encode()).hexdigest()


def insecure_file_access(filename):
    # Path traversal possibility
    with open("/tmp/" + filename) as f:
        return f.read()