FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 10000
# Un solo proceso con varios hilos: el despachador de pagos vive dentro de ese proceso.
CMD exec gunicorn -w 1 --threads 8 --timeout 60 -b 0.0.0.0:${PORT} app:app
