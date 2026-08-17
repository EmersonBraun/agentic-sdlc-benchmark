FROM node:22.13.0-bookworm-slim AS verify

WORKDIR /app

RUN apt-get update \
  && apt-get install --yes --no-install-recommends openssl \
  && rm -rf /var/lib/apt/lists/*

RUN npm install --global pnpm@11.21.0

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ENV DATABASE_URL=postgresql://app:app@localhost:5432/agentic_sdlc_greenfield

RUN pnpm prisma:validate \
  && pnpm prisma:generate \
  && pnpm lint \
  && pnpm test \
  && pnpm build
