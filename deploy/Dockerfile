FROM python:3.11-slim

# Variables de entorno para Python en contenedores
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema y Chromium para renderizado headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    chromium \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar requerimientos primero para aprovechar la caché de capas Docker
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código del repositorio
COPY . .

# Asegurar directorios de persistencia
RUN mkdir -p data output logs assets

EXPOSE 8000

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--access-log"]
