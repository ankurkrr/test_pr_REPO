# test_resource_leak.py

import sqlite3


def fetch_data():

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users")

    results = cursor.fetchall()

    # Connection never closed
    return results