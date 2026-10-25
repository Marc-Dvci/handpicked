# Handpicked: one container serving the API and the built web app.
#   docker build -t handpicked .
#   docker run -p 8080:8080 handpicked                      # replay mode, no keys
#   docker run -p 8080:8080 -e YOUCAM_API_KEY=... -e DASHSCOPE_API_KEY=... handpicked

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 HANDPICKED_VAR=/app/var
# mediapipe pulls in the full OpenCV build, which links against libGL and glib
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml LICENSE ./
COPY handpicked ./handpicked
COPY assets ./assets
COPY eval/results ./eval/results
COPY --from=web /web/dist ./web/dist
# Measure the seven sample hands at build time, so the first visitor does not wait for it.
RUN python -c "from handpicked.service import Handpicked; h = Handpicked(); h.samples(); h.close()" \
    && useradd --create-home --uid 10001 app && chown -R app /app/var
USER app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn handpicked.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
