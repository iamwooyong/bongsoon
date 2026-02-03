FROM python:3.11-slim

WORKDIR /app

# git 설치 및 safe directory 설정
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/* \
    && git config --global --add safe.directory /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 및 git 복사
COPY . .

CMD ["python", "stock_bot.py"]
