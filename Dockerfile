FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY image_flux2_working.json .
COPY backend/ backend/
COPY frontend/ frontend/

RUN mkdir -p storage/uploads storage/outputs storage/temp

EXPOSE 8000

CMD ["python", "app.py"]
