FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    PORT=7860

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY guandan_model ./guandan_model
COPY data ./data

EXPOSE 7860

CMD ["python", "app.py"]
