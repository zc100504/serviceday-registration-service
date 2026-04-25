FROM python:3.13.1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD sh -c "python manage.py migrate && python manage.py runserver 0.0.0.0:${PORT:-8000}"