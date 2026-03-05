import json
import sqlite3

# Architecture Alert: Database direct access in a presentation layer
def render_user_page():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    
    html = "<html><body><h1>User List</h1><ul>"
    for u in users:
        html += f"<li>{u[1]}</li>"
    html += "</ul></body></html>"
    return html

# Code Reuse Alert: Re-implementing JSON parsing
def parse_json_string(json_str):
    try:
        return json.loads(json_str)
    except:
        return None
