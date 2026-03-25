FROM public.ecr.aws/docker/library/node:20-alpine AS build

WORKDIR /app
ARG VITE_BACKEND_BASE_URL=http://localhost:4000
ENV VITE_BACKEND_BASE_URL=${VITE_BACKEND_BASE_URL}

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM public.ecr.aws/docker/library/nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
