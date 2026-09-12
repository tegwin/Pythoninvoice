FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Build tools are only needed while pip compiles wheels; drop them afterwards
# so they don't ship in the final image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libjpeg-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# gunicorn is added here rather than in requirements.txt: it is only needed
# for the container/production path, not for a local dev run of run.py.
RUN pip install --no-cache-dir -r requirements.txt gunicorn \
 && apt-get purge -y gcc && apt-get autoremove -y

COPY . .

RUN chmod +x /app/docker-entrypoint.sh \
 && mkdir -p /app/data /app/static/uploads

EXPOSE 5000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# 2 workers with 4 threads each suits a small install. The app keeps a MySQL
# pool of 5 per process, so raise pool_size in database.py before adding workers.
# Railway injects PORT; compose has no PORT so it falls back to 5000.
# sh -c so $PORT expands at runtime rather than being a literal.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} \
     --workers 2 --threads 4 --timeout 120 \
     --access-logfile - --error-logfile - app_web:app"]
