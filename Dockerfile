# Dockerfile for Streamlit app with ffmpeg
FROM python:3.11-slim

# Install ffmpeg and basic build tools
RUN apt-get update && apt-get install -y ffmpeg build-essential && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the repository contents into the image
COPY . /app

# Expose port used by Streamlit (we'll use 10000)
EXPOSE 10000

# Streamlit environment variables
ENV PORT=10000
ENV STREAMLIT_SERVER_PORT=10000
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Start Streamlit
CMD ["streamlit", "run", "streamlit_app.py"]