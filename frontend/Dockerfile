# ── Stage 1: install ALL dependencies (including devDeps needed for build) ────
FROM node:20-alpine AS deps
WORKDIR /app

# Copy manifests
COPY package.json package-lock.json ./

# Use npm install (not npm ci) — more tolerant of nested peer dep lockfile quirks.
# --legacy-peer-deps avoids conflicts in the React/Next.js ecosystem.
# NOT setting NODE_ENV=production so devDependencies (tailwindcss, postcss, autoprefixer)
# are installed — they are required at Next.js build time.
RUN npm install --legacy-peer-deps

# ── Stage 2: build ─────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are inlined at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# tailwindcss/postcss/autoprefixer are in node_modules from stage 1 ✓
RUN npm run build

# ── Stage 3: lean production runtime ──────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next        ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public       ./public

EXPOSE 3000
CMD ["npm", "start"]

# ── Stage 4: development (docker compose dev server) ──────────────────────────
FROM node:20-alpine AS dev
WORKDIR /app
ENV NODE_ENV=development
COPY package.json package-lock.json ./
RUN npm install --legacy-peer-deps
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]
