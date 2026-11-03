FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/backend

# Copy dependency metadata first so code changes do not reinstall packages.
COPY pyproject.toml requirements.lock ./

# The optional extra_ca secret supports networks that inspect HTTPS traffic. It is
# used for this step only and is not stored in the image. See
# docker-compose.override.example.yml.
RUN --mount=type=secret,id=extra_ca,required=false sh -ec '\
    if [ -s /run/secrets/extra_ca ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/ca-bundle.pem; \
        export PIP_CERT=/tmp/ca-bundle.pem; \
    fi; \
    mkdir app; \
    touch app/__init__.py; \
    pip install --no-cache-dir --root-user-action=ignore -c requirements.lock .; \
    rm -rf app build ./*.egg-info /tmp/ca-bundle.pem'

COPY alembic.ini ./
COPY app ./app
COPY data ./data

RUN useradd --system --no-create-home nourisearch
USER nourisearch

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
