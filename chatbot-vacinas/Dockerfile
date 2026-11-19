FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VACINA_DB_PATH=/data/lembretes.sqlite3

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY data/*.json ./data/

# /data recebe o volume persistente com o SQLite. O processo roda como root
# porque volumes do Railway são montados com dono root.
RUN mkdir -p /data

CMD ["python", "bot.py"]
