# Use the official Python base image
FROM python:latest
# root directory is passed as argument in $HOST_PATH
# RUN mkdir -p /app
WORKDIR /app
# create the directory where host directories will be mounted

# Copy the requirements file to the working directory
# COPY requirements.txt .
COPY requirements.txt ./
# RUN cat requirements.txt
# Install the Python dependencies
# RUN pip install "fastapi[standard]"
# RUN pip install -r requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
RUN pip install fastapi uvicorn

# Copy the application code to the working directory
COPY . .
# RUN ls app
# Expose the port on which the application will run
EXPOSE 8080

# Run the FastAPI application using uvicorn server
# CMD ["uvicorn", "fastapi:app", "--host", "0.0.0.0", "--port", "8000"]
# CMD ["uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
CMD ["fastapi", "run", "main.py", "--port", "8000"]
