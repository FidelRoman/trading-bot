FROM --platform=linux/amd64 python:3.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-bot.txt scripts/fix_forexconnect_linux.sh ./
RUN python -m pip install --no-cache-dir --upgrade "pip<24.1" \
    && python -m pip install --no-cache-dir -r requirements-bot.txt \
    && sh fix_forexconnect_linux.sh

COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "tradingbot.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
