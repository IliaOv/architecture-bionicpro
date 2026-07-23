# Build Yandex OAuth2 IdP provider (без scope openid)
FROM maven:3.9.6-eclipse-temurin-17 AS provider-build
WORKDIR /src
COPY yandex-provider/pom.xml .
COPY yandex-provider/src ./src
RUN mvn -q -DskipTests package && cp target/keycloak-yandex-provider-*.jar /provider.jar

FROM quay.io/keycloak/keycloak:21.1.2
COPY --from=provider-build /provider.jar /opt/keycloak/providers/keycloak-yandex-provider.jar
