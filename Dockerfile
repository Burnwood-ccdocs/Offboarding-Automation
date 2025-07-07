FROM python:3.11-slim

# Install system dependencies needed for cron, Chromium (for selenium), and any build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        cron \
        ca-certificates \
        curl \
        gnupg \
        chromium \
        chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy project files into the container
COPY . /app

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy crontab file and set up cron job
COPY crontab.txt /etc/cron.d/offboarding-cron
RUN chmod 0644 /etc/cron.d/offboarding-cron && \
    crontab /etc/cron.d/offboarding-cron

# Ensure cron logs are printed to container logs
RUN touch /var/log/cron.log

# Run get_users.py once, then start cron in the foreground
CMD ["bash", "-c", "python get_users.py & cron -f"] 