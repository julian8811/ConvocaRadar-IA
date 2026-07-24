FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build
CMD ["sh", "-c", "npm run start -- --port ${PORT:-3000}"]
