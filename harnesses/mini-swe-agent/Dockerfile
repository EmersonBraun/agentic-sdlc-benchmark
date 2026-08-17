FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ARG MINI_SWE_AGENT_VERSION=2.4.6

RUN pip install --no-cache-dir "mini-swe-agent==${MINI_SWE_AGENT_VERSION}"

ENTRYPOINT ["mini"]
