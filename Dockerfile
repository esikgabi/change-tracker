FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY watcher.py .
RUN adduser -D app && mkdir /data && chown app /data
USER app
ENV PYTHONUNBUFFERED=1
CMD ["python", "watcher.py"]
