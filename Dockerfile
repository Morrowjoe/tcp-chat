FROM python:3.12-slim
WORKDIR /app
COPY server.py client.py ./
EXPOSE 5000
ENV CHAT_HOST=0.0.0.0 CHAT_PORT=5000
CMD ["python", "-u", "server.py"]
