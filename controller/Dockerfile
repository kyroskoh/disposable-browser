FROM python:3.12-slim AS build
WORKDIR /src
COPY controller/pyproject.toml controller/
COPY controller/src controller/src

RUN pip install --no-cache-dir --prefix=/install ./controller

FROM python:3.12-slim
COPY --from=build /install /usr/local
# Docker socket access is granted at runtime via `group_add` (see docker-compose.yml).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin dbrowser
USER 10001
ENV PYTHONUNBUFFERED=1 \
    HOME=/tmp
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"
ENTRYPOINT ["dbrowser"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
