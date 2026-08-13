#!/bin/sh
set -eu

load_secret() {
    name="$1"
    default_path="$2"
    file_variable="$name"_FILE
    value="$(printenv "$name" 2>/dev/null || true)"

    if [ -z "$value" ]; then
        secret_path="$(printenv "$file_variable" 2>/dev/null || printf '%s' "$default_path")"
        if [ ! -r "$secret_path" ]; then
            echo "Erro: defina $name ou disponibilize o segredo em $secret_path." >&2
            exit 1
        fi
        value="$(tr -d '\r\n' < "$secret_path")"
    fi

    if [ -z "$value" ]; then
        echo "Erro: $name não pode ficar vazio." >&2
        exit 1
    fi
    export "$name=$value"
}

load_secret DOU_WEB_USERNAME /run/secrets/dou_web_username
load_secret DOU_WEB_PASSWORD /run/secrets/dou_web_password

mkdir -p /app/downloads
chown scraper:scraper /app/downloads
umask 027

exec setpriv --reuid=scraper --regid=scraper --init-groups -- "$@"
