FROM python:3.12-slim

WORKDIR /src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Actual startup is via docker-compose; this default just gives a usable shell.
CMD ["/bin/bash"]
