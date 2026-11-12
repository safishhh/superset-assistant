FROM python:3.11.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY src ./src
ENV PYTHONPATH=/app/src

EXPOSE 28088
CMD ["uvicorn", "assistant_agent.main:app", "--host", "0.0.0.0", "--port", "28088"]
