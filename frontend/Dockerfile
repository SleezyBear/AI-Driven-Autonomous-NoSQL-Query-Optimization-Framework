FROM --platform=linux/amd64 node:22.14.0-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM --platform=linux/amd64 nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
COPY --chown=101:101 frontend/nginx.conf /etc/nginx/conf.d/default.conf
USER 101:101
EXPOSE 8080
