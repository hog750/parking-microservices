FROM python:3.10-slim

# Устанавливаем зависимости и Microsoft ODBC Driver 17
RUN apt-get update && apt-get install -y curl gnupg2 apt-transport-https unixodbc-dev \
    && mkdir -p /usr/share/keyrings \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/microsoft-prod.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем requirements.txt и устанавливаем библиотеки
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r requirements.txt

# Теперь копируем остальной код
COPY . .

EXPOSE 5002
CMD ["python", "app.py"]
