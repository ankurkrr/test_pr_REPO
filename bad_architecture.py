import json
import sqlite3
from collections import defaultdict

# Architecture Alert: Database direct access in a web layer
# (Caught by ArchitectureChecker)
def fetch_users_from_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    return cursor.fetchall()

# Architecture Alert: Mixing logic and presentation
def render_user_page(user_id):
    users = fetch_users_from_db()
    html = "<html><body><h1>User List</h1><ul>"
    for u in users:
        html += f"<li>{u[1]}</li>"
    html += "</ul></body></html>"
    return html

# Code Reuse Alert: Re-implementing JSON parsing
# (Caught by ReuseChecker)
def parse_json_string(json_str):
    try:
        # We should just use json.loads, this is a redundant wrapper
        return json.loads(json_str)
    except:
        return None

# Logic Error: Mutable default argument (Caught by LLM / Flake8)
def append_to_list(item, my_list=[]):
    my_list.append(item)
    return my_list

# Hardcoded API Endpoint (Caught by SAST)
API_ENDPOINT = "http://api.example.com/v1/internal/data"

def fetch_data():
    import requests
    # Security Alert: Missing timeout in requests call (Caught by Bandit/LLM)
    response = requests.get(API_ENDPOINT)
    return response.json()
