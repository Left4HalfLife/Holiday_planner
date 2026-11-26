FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/holidays.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 planner \
    && useradd --uid 10001 --gid planner --no-create-home planner \
    && mkdir -p /app/data

COPY app ./app
COPY docker-entrypoint.py .

EXPOSE 5000
ENTRYPOINT ["python", "/app/docker-entrypoint.py"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
