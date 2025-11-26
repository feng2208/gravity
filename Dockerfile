# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables for Python best practices
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Create a non-root user and group
RUN addgroup --system app && adduser --system --ingroup app app

# Set the working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Change ownership of the application directory
RUN chown -R app:app /app

# Switch to the non-root user
USER app

# Expose the port the app runs on
EXPOSE 3001

# Run the application using uvicorn for production
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3001"]
