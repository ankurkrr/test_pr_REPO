# test_architecture.py

import sqlite3


# Presentation layer should not access DB directly
def render_page():

    conn = sqlite3.connect("users.db")

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users")

    users = cursor.fetchall()

    html = "<html><body>"

    for u in users:
        html += "<p>" + str(u) + "</p>"

    html += "</body></html>"

    return html