import os
import subprocess
import hashlib

# High Alert: Hardcoded secrets (Caught by SAST / Bandit)
AWS_SECRET_KEY = "AKIAIOSFODNN7EXAMPLE"
DB_PASSWORD = "super_secret_password_123"

def get_user_data(user_id):
    # Security Alert: SQL Injection vulnerability (Caught by LLM / Bandit)
    query = "SELECT * FROM users WHERE id = " + str(user_id)
    print("Executing:", query)
    return query

def execute_system_command(cmd):
    # Security Alert: OS Command Injection (Caught by Bandit)
    return subprocess.call(cmd, shell=True)

def poorly_formatted_function():
    x=1
    y =2 
    if x==y:
     print("Math is broken")
    # Missing docstring, bad spacing (Caught by Flake8)

def process_payment(amount, user_id, credit_card):
    # Logic Error / Security: Logging sensitive PII (Caught by LLM / Rules)
    print(f"Processing ${amount} for {user_id} with card {credit_card}")
    
    # Logic Error: No validation on amount (Caught by LLM)
    new_balance = 1000 - amount
    return new_balance

def md5_hashing(password):
    # Security Alert: Weak hashing algorithm (Caught by Bandit / SAST)
    return hashlib.md5(password.encode()).hexdigest()

class user_manager:
    # Style Alert: Class names should use CamelCase (Caught by Flake8)
    def __init__(self, name):
        self.name = name

# Execution block
if __name__ == '__main__':
    poorly_formatted_function()
    execute_system_command("echo Hello")
