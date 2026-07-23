# Build stage
FROM node:16-alpine as build

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# CRA вшивает REACT_APP_* на этапе сборки
ARG REACT_APP_AUTH_URL=http://localhost:8000
ARG REACT_APP_KEYCLOAK_URL=http://localhost:8080
ARG REACT_APP_KEYCLOAK_REALM=reports-realm
ARG REACT_APP_KEYCLOAK_CLIENT_ID=reports-frontend
ARG REACT_APP_OIDC_REDIRECT_URI=http://localhost:3000/callback
ENV REACT_APP_AUTH_URL=$REACT_APP_AUTH_URL \
    REACT_APP_KEYCLOAK_URL=$REACT_APP_KEYCLOAK_URL \
    REACT_APP_KEYCLOAK_REALM=$REACT_APP_KEYCLOAK_REALM \
    REACT_APP_KEYCLOAK_CLIENT_ID=$REACT_APP_KEYCLOAK_CLIENT_ID \
    REACT_APP_OIDC_REDIRECT_URI=$REACT_APP_OIDC_REDIRECT_URI

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
