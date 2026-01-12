"""
Minimal Django settings for running tests.

This allows the package tests to run standalone without being inside a Django project.
"""

SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "django_agent_runtime",
]

import os

# Use PostgreSQL for async tests if available, otherwise SQLite
if os.environ.get("USE_POSTGRES_FOR_TESTS"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "django_agent_runtime_test"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "letmein"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

ROOT_URLCONF = "tests.urls"

# Use the default Django user model
AUTH_USER_MODEL = "auth.User"

# Minimal DRF settings
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# Agent runtime settings
AGENT_RUNTIME = {
    "DEFAULT_MODEL_PROVIDER": "openai",
    "DEFAULT_MODEL": "gpt-4o",
    "QUEUE_BACKEND": "memory",
    "EVENT_BUS_BACKEND": "memory",
    "STATE_STORE_BACKEND": "memory",
}

# Required for Django 3.2+
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Timezone
USE_TZ = True
TIME_ZONE = "UTC"

