# حسابیار — بات تلگرام حسابداری (داده روی Google Sheets)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/mpl

WORKDIR /app

# نصب وابستگی‌ها (لایه‌ی کش‌شونده). tzdata از requirements می‌آید.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کد برنامه (شامل فونت وزیرمتن در hesabyar/pdf/fonts)
COPY hesabyar ./hesabyar

# فرایند worker است (long polling)، نه وب‌سرور؛ هیچ پورتی expose نمی‌شود.
CMD ["python", "-m", "hesabyar"]
