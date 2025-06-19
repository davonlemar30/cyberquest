# Use a slim Python base image
FROM python:3.10-slim

# Create a working directory in the container
WORKDIR /app

# Copy requirements file first (if you have one)
COPY requirements.txt /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot code
COPY . /app

# Set the environment variable for PORT (Cloud Run uses 8080 by default)
ENV PORT=8080

# If you're using Socket Mode, your code will just keep running.
# If you switch to HTTP mode, you might do: CMD ["python", "slacky2.py", "--port=8080"]
CMD ["python", "slacky2.py"]
