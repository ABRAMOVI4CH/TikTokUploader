FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        libnss3 \
        libatk-bridge2.0-0 \
        libgtk-3-0 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libasound2t64 \
        libpangocairo-1.0-0 \
        xvfb \
        tigervnc-standalone-server \
        tigervnc-tools \
        dbus-x11 \
        autocutsel \
        xclip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh && mkdir -p /app/uploads

ENV CHROME_BINARY=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV DISPLAY=:99

EXPOSE 5000 5001 5900

ENTRYPOINT ["./entrypoint.sh"]
