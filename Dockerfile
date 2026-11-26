# Runs the demo desk with the recorded run bundled in web/data/run.json.
# The page still reads the mandate balance live from Aevum over RPC.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8787
EXPOSE 8787
CMD ["python3", "server/app.py"]
