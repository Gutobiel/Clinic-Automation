FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY core ./core
COPY tenants ./tenants
COPY hermes ./hermes
COPY scripts ./scripts

RUN mkdir -p /app/data /app/storage_state /app/downloads /app/screenshots

EXPOSE 8080

CMD ["uvicorn", "core.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
