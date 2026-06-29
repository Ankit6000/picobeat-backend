FROM node:22-alpine

WORKDIR /build

# Install build deps needed by cobalt
RUN apk add --no-cache python3 alpine-sdk git

# Clone cobalt source
RUN git clone --depth 1 https://github.com/imputnet/cobalt.git .

# Enable corepack for pnpm
RUN corepack enable

# Install dependencies and deploy API
RUN pnpm install --prod --frozen-lockfile
RUN pnpm deploy --filter=@imput/cobalt-api --prod /app

# Copy .git for version info  
WORKDIR /app
RUN cp -r /build/.git /app/.git

# Clean up build dir to save space
RUN rm -rf /build

# Render uses PORT env var (default 10000)
# Cobalt uses API_PORT
ENV API_PORT=10000
ENV API_URL="https://picobeat-backend.onrender.com/"
ENV CORS_WILDCARD=1

# NO Turnstile/JWT vars = no authentication required (open API)
# This is what makes it work without browser CAPTCHAs

USER node
EXPOSE 10000
CMD ["node", "src/cobalt"]
