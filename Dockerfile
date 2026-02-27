FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY app ./app

CMD exec gunicorn --bind :${PORT:-8080} --workers 2 --threads 4 --timeout 0 app.main:app
