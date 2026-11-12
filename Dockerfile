FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY app/ ./app/
COPY data/ ./data/
COPY static/ ./static/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# geoalchemy2 0.17.1 bug: uses ColumnCollection() which became abstract in SQLAlchemy 2.1
# https://github.com/geoalchemy/geoalchemy2/issues/xxx — patch until upstream releases a fix
RUN sed -i \
    's/from sqlalchemy.sql import expression/from sqlalchemy.sql import expression\nfrom sqlalchemy.sql.base import DedupeColumnCollection as _DedupeColumnCollection/' \
    .venv/lib/python3.12/site-packages/geoalchemy2/admin/dialects/common.py && \
    sed -i \
    's/column_collection = expression\.ColumnCollection()/column_collection = _DedupeColumnCollection()/' \
    .venv/lib/python3.12/site-packages/geoalchemy2/admin/dialects/common.py

CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
