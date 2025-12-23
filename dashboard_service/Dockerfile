FROM python:3.10-slim

WORKDIR /app

# зависимости python
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y curl

# код + шаблоны
COPY app.py ./app.py
COPY templates ./templates

EXPOSE 8080
CMD ["python", "app.py"]
