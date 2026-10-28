# Build context is the repo root: az acr build -f src/chat-backend/Dockerfile .
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY src/chat-backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/chat-backend/app.py src/chat-backend/guardrails.py src/chat-backend/telemetry.py src/chat-backend/admin.py ./
COPY --from=ui /ui/dist ./static
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
