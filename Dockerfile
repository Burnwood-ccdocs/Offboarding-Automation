# Use an official lightweight Python image as the base
FROM python:3.11-slim

# Create a non-root user `sarthak` to own and run the scripts
RUN useradd -ms /bin/bash sarthak

# Set the working directory
WORKDIR /app

# Copy the project files into the image
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Switch to the non-root user for runtime
RUN chown -R sarthak:sarthak /app

USER sarthak

# Launch the Slack bot (which now refreshes tokens in a background thread)
CMD ["python", "get_users.py"] 