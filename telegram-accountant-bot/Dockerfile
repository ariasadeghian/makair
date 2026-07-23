# حسابیار — بات تلگرام حسابداری
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/mpl \
    DATABASE_URL=sqlite:////app/data/hesabyar.db

WORKDIR /app

# نصب وابستگی‌ها (لایه‌ی کش‌شونده)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کد برنامه (شامل فونت وزیرمتن در hesabyar/pdf/fonts)
COPY hesabyar ./hesabyar

# مسیر داده برای دیتابیس و پشتیبان‌ها
RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "hesabyar"]
