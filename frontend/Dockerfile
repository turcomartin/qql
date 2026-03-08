# Stage 1: build
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
RUN npm run build

# Stage 2: serve with nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html

# nginx config: serve index.html for all routes (SPA fallback)
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
    # Proxy API routes to backend\n\
    location ~ ^/(chat|health|eda|tables) {\n\
        proxy_pass http://backend:8000;\n\
        proxy_set_header Host $host;\n\
        proxy_set_header X-Real-IP $remote_addr;\n\
        # Required for SSE streaming\n\
        proxy_buffering off;\n\
        proxy_cache off;\n\
        proxy_read_timeout 120s;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
