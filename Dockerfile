# Example Dockerfile for running django-agent-runtime in production
#
# This example uses supervisor to run both:
# - Daphne (ASGI web server for Django Channels / async support)
# - runagent (the agent worker process)
#
# Customize this for your project's needs.

FROM python:3.11-slim

ENV APP_HOME=/app
WORKDIR $APP_HOME

# Install system dependencies
# - libpq-dev: PostgreSQL client library (if using PostgreSQL)
# - supervisor: Process manager to run multiple services
RUN apt-get update --yes --quiet && apt-get install --yes --quiet --no-install-recommends \
    build-essential \
    libpq-dev \
    supervisor \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Collect static files (if your project uses them)
RUN python manage.py collectstatic --noinput

# Default port - override with PORT environment variable
ENV PORT=8080

# Ensure Python output is sent straight to terminal
ENV PYTHONUNBUFFERED=1

# Django settings module - set this to your production settings
# ENV DJANGO_SETTINGS_MODULE=myproject.settings.production

# Copy supervisor configuration and start supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
