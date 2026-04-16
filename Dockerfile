FROM python:3.10-slim

WORKDIR /app

# Install FFmpeg just in case (though encoding is on GitHub, ffprobe might be needed in future)
RUN apt-get update && apt-get install -y ffmpeg

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["python", "main.py"]
