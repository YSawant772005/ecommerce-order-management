# Single-container image: PostgreSQL + MongoDB + Elasticsearch + RabbitMQ +
# FastAPI + Celery worker/beat + nginx, supervised together.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    postgresql-16 rabbitmq-server supervisor nginx curl \
    python3 python3-venv ca-certificates \
  && rm -rf /var/lib/apt/lists \
  && useradd -m -s /bin/bash es

RUN curl -fsSL https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-ubuntu2204-7.0.14.tgz -o /tmp/mongo.tgz \
  && mkdir -p /opt/mongo && tar -xzf /tmp/mongo.tgz -C /opt/mongo --strip-components=1 \
  && rm /tmp/mongo.tgz

RUN curl -fsSL https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-8.13.4-linux-x86_64.tar.gz -o /tmp/es.tgz \
  && mkdir -p /opt/es && tar -xzf /tmp/es.tgz -C /opt/es --strip-components=1 \
  && rm /tmp/es.tgz && chown -R es:es /opt/es

RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install -q --upgrade pip

COPY backend/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -q -r /tmp/requirements.txt

COPY backend /app/backend
COPY frontend/dist /usr/share/nginx/html
COPY deploy/nginx.single.conf /etc/nginx/sites-available/app
COPY deploy/supervisord.conf /etc/supervisor/conf.d/app.conf
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
  && rm -f /etc/nginx/sites-enabled/default \
  && ln -s /etc/nginx/sites-available/app /etc/nginx/sites-enabled/app

VOLUME /data
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
