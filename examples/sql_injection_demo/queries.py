"""Benchmark fixture: SQL injection via string formatting."""
import sqlite3


def connect():
    return sqlite3.connect(":memory:")


def find_user_by_name(connection, name):
    """Look up a user by name.

    The query is built with string formatting, so a crafted ``name`` can alter
    the statement. This is the vulnerability the benchmark issue describes.
    """
    cursor = connection.cursor()
    cursor.execute("SELECT id, email FROM users WHERE name = '%s'" % name)
    return cursor.fetchone()


def find_user_by_id(connection, user_id):
    """The parameterised version, kept for contrast."""
    cursor = connection.cursor()
    cursor.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()
