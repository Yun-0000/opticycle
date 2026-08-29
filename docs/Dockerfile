# syntax=docker/dockerfile:1
# Official Alpaca CLI fallback binary pin (paper default).
FROM debian:bookworm-slim
ARG ALPACA_CLI_TAG=v0.0.14
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://github.com/alpacahq/cli/releases/download/${ALPACA_CLI_TAG}/alpaca_linux_amd64.tar.gz" \
      | tar -xz -C /usr/local/bin \
    && chmod +x /usr/local/bin/alpaca || true
ENV ALPACA_LIVE_TRADE=false
ENV ALPACA_OUTPUT=json
