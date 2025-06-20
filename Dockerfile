FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
EXPOSE 8080
ENV PORT=8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "slacky2:flask_app"]
