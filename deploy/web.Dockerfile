FROM node:22-bookworm-slim AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

ARG GIT_COMMIT=unknown
ARG DESK_TREE=unknown
LABEL desk.schema="3" \
      desk.commit="${GIT_COMMIT}" \
      desk.tree="${DESK_TREE}"

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
USER root
RUN printf '%s\n' "{\"commit\":\"${GIT_COMMIT}\",\"tree\":\"${DESK_TREE}\",\"schema\":3}" > /usr/share/nginx/html/desk-build.json \
 && chown nginx:nginx /usr/share/nginx/html/desk-build.json
USER nginx

EXPOSE 8080
