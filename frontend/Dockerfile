FROM --platform=linux/amd64 node:22.14.0-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM --platform=linux/amd64 nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
