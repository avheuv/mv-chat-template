FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
# We copy everything so the backend folder is the context root
COPY . .

# Expose port (Cloud Run expects 8080 by default)
EXPOSE 8080

# Command to run the Uvicorn application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
