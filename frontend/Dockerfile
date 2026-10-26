# syntax=docker/dockerfile:1

# ---------- build ----------
FROM node:20.18.1-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY index.html tsconfig.json vite.config.js ./
COPY src ./src
RUN npm run build

# ---------- runtime ----------
# nginx-unprivileged слушает 8080 и стартует под uid 101 (не root).
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
COPY --from=build /app/dist /usr/share/nginx/html
COPY --chown=101:101 frontend/nginx.conf /etc/nginx/conf.d/default.conf
USER 101

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
