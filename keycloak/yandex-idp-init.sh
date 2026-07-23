#!/bin/sh
# Прописывает clientId/clientSecret Яндекс ID в Keycloak IdP после старта.
# Требует: KEYCLOAK_URL, KEYCLOAK_ADMIN, KEYCLOAK_ADMIN_PASSWORD,
#          YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET, REALM

set -eu

KC_URL="${KEYCLOAK_URL:-http://keycloak:8080}"
REALM="${REALM:-reports-realm}"
ADMIN="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
YID="${YANDEX_CLIENT_ID:-}"
YSEC="${YANDEX_CLIENT_SECRET:-}"

echo "Ожидание Keycloak..."
until curl -sf "$KC_URL/realms/master" >/dev/null; do sleep 3; done
sleep 5

if [ -z "$YID" ] || [ "$YID" = "changeme" ] || [ -z "$YSEC" ] || [ "$YSEC" = "changeme" ]; then
  echo "YANDEX_CLIENT_ID/SECRET не заданы (или changeme) — IdP yandex остаётся с заглушкой."
  echo "Задайте переменные окружения и перезапустите keycloak-yandex-init."
  exit 0
fi

echo "Получение admin-токена..."
TOKEN=$(curl -sf -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" \
  -d "username=$ADMIN" \
  -d "password=$ADMIN_PASS" \
  -d "grant_type=password" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')

if [ -z "$TOKEN" ]; then
  echo "Не удалось получить admin-токен"
  exit 1
fi

echo "Обновление IdP yandex..."
# Получаем текущий конфиг и патчим секреты
CUR=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "$KC_URL/admin/realms/$REALM/identity-provider/instances/yandex")

# Минимальный PATCH через PUT с подстановкой — используем Admin API update config keys
curl -sf -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$KC_URL/admin/realms/$REALM/identity-provider/instances/yandex" \
  -d "$(printf '%s' "$CUR" | sed "s/\"clientId\"[[:space:]]*:[[:space:]]*\"[^\"]*\"/\"clientId\":\"$YID\"/" | sed "s/\"clientSecret\"[[:space:]]*:[[:space:]]*\"[^\"]*\"/\"clientSecret\":\"$YSEC\"/")" \
  >/dev/null

echo "IdP yandex обновлён (clientId=$YID)."
