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

# 8080 matches what Choreo injects at runtime, so the image default and the
# port declared in .choreo/component.yaml agree even if the injection ever goes
# away. server.py still honours PORT, so an explicit override wins over this.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
