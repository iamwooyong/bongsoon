FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stock_bot.py .

CMD ["python", "stock_bot.py"]
