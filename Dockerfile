FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    CACHE_DIR=/app/.cache \
    USER_DATA_DIR=/app/user_data

WORKDIR /app

# TORCH_INDEX: CPU by default (small image). For NVIDIA GPUs build with
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install torch --index-url ${TORCH_INDEX}

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd -m appuser && mkdir -p /models/hf /app/.cache /app/user_data \
    && chown -R appuser /app /models
USER appuser

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1
CMD ["streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
