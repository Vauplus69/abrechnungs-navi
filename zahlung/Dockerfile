FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY lib.mjs server.mjs ./
COPY test ./test
USER node
CMD ["node", "server.mjs"]
