FROM python:3.11-slim

# Choreo rejects root-run images; it requires a numeric UID in 10000-20000.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER 10001

# main.py reads PORT and falls back to 8000. Keep the declared Choreo endpoint
# port, this ENV, and any platform-injected PORT in agreement — a mismatch is
# what left this agent listening on 8080 while its endpoint config said 8000,
# so probes never reached it and the pod was recycled every few minutes.
ENV PORT=8000
EXPOSE 8000

CMD ["python", "main.py"]
