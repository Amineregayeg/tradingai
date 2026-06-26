# ─── Dev stage (default) ─────────────────────────────────────────────────────
FROM node:20-alpine AS dev

# Install pnpm globally
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Install dependencies first (layer-cached until lockfile changes)
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# Copy the rest of the source code
COPY . .

EXPOSE 5173

CMD ["pnpm", "dev", "--host"]
