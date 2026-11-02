"""
Database settings from .streamlit/secrets.toml (section [database]), overridden by environment variables.
The committed .streamlit/secrets.example.toml shows the keys; the real file is gitignored.
"""
import os
import pathlib
import tomllib

SECRETS = pathlib.Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
ENVIRONMENT = {"server": "PORTAL_DB_SERVER", "database": "PORTAL_DB_NAME",
               "username": "PORTAL_DB_USER", "password": "PORTAL_DB_PASSWORD"}


def database_settings():
    settings = {"server": "localhost", "database": "NorthGridPortal"}
    if SECRETS.exists():
        settings.update(tomllib.loads(SECRETS.read_text(encoding="utf-8")).get("database", {}))
    settings.update({key: os.environ[name] for key, name in ENVIRONMENT.items() if os.environ.get(name)})
    return settings
