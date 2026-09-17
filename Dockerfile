FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/uploads /app/state

ENV CHROME_BINARY=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV HEADLESS=true
ENV PYTHONUNBUFFERED=1

EXPOSE 5000 5001

CMD ["python", "-m", "flask", "--app", "api.server", "run", "--host=0.0.0.0", "--port=5000"]
