FROM python:3.11-slim

# Choreo rejects images that run as root; it requires a numeric UID in the
# 10000-20000 range. Create the user before installing so nothing lands in a
# root-only path.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER 10001

# Honour the platform-injected PORT; 9000 is only the local default. Hardcoding
# a port is what left the agent listening on 8080 while its endpoint config
# still said 8000.
ENV PORT=9000
EXPOSE 9000

CMD ["python", "server.py"]
