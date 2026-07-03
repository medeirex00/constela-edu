# SGPE — Web (build estático servido por nginx, com proxy /api para o backend)
FROM node:22-slim AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY apps/desktop/package.json apps/desktop/
COPY apps/mobile/package.json apps/mobile/
COPY packages/core/package.json packages/core/
RUN npm ci --no-audit --no-fund --legacy-peer-deps --ignore-scripts
COPY packages ./packages
COPY apps/web ./apps/web
RUN npm run build --workspace @sgpe/web

FROM nginx:1.27-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 80
