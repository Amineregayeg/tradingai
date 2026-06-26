"""Unit-test conftest: set DATABASE_URL to SQLite before any app module is imported.

The top-level conftest.py also overrides the URL, but app/db/__init__.py
eagerly calls create_async_engine() at import time using the *settings* object
(which reads from the environment).  Setting DATABASE_URL here — before any
app code is imported — prevents the asyncpg driver from being required for
pure unit tests that never touch a real database.
"""
import os

# Must happen before any app module is imported.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
