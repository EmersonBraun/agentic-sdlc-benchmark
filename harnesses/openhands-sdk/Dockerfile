FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ARG OPENHANDS_VERSION=1.42.1

RUN pip install --no-cache-dir \
    "openhands-sdk==${OPENHANDS_VERSION}"

CMD ["python", "-c", "import openhands.sdk; print('openhands-sdk import ok')"]
