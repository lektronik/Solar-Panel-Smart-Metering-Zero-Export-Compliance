FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN useradd -r -s /bin/false appuser
COPY --from=build /install /usr/local
WORKDIR /app
COPY src/ src/
COPY config.yaml .
USER appuser
ENV PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('localhost',8080)); s.close()" || exit 1
ENTRYPOINT ["python", "-m", "src.main"]
