# Use the official Python base image

FROM python:latest
RUN mkdir -p /app
WORKDIR /app
# create the directory where host directories will be mounted
RUN mkdir -p /host
RUN mkdir -p /host/fastapi
RUN mkdir -p /host/var

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file to the working directory
COPY requirements.txt .

# Install the Python dependencies
RUN pip install -r requirements.txt

# Copy the application code to the working directory
COPY . .

# Expose the port on which the application will run
EXPOSE 8080

# Run the FastAPI application using uvicorn server
CMD ["uvicorn", "fastapi:app", "--host", "0.0.0.0", "--port", "8080"]

