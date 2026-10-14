#!/usr/bin/env bash
# Lead Radar: the one way to set up, start, back up and restore a local single-user registry.
#
#   scripts/lead-radar.sh start              # first run: builds, writes .env, migrates, serves
#   scripts/lead-radar.sh backup             # consistent copy of the DB + the encryption key
#   scripts/lead-radar.sh restore <dir>      # put a backup back (refuses while the server runs)
#
# Serves on 127.0.0.1 only. Secrets are generated into .env (mode 600) and never printed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-18790}"
ENV_FILE="$ROOT/.env"
BACKUP_DIR="${LEAD_RADAR_BACKUPS:-$ROOT/backups}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Eksik: $1 ($2)" >&2; exit 1; }; }

ensure_env() {
  if [[ -f "$ENV_FILE" ]] && grep -q '^TREG_SECRET_KEY=.\+' "$ENV_FILE"; then
    return
  fi
  [[ -f "$ENV_FILE" ]] && { echo ".env var ama TREG_SECRET_KEY boş; düzeltin veya dosyayı kaldırın." >&2; exit 1; }
  umask 077
  local key token
  key="$(uv run --frozen python -m treg keygen)"
  token="$(uv run --frozen python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -e "s|^TREG_SECRET_KEY=.*|TREG_SECRET_KEY=$key|" \
      -e "s|^TREG_API_TOKEN=.*|TREG_API_TOKEN=$token|" .env.leads.example > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo ".env oluşturuldu (anahtarlar ekrana yazılmadı). Bu dosyayı yedekleyin; anahtar olmadan kayıtlı API anahtarları çözülemez."
}

load_env() { set -a; # shellcheck disable=SC1090
  . "$ENV_FILE"; set +a; }

db_file() {
  local url="${TREG_DATABASE_URL:-sqlite+aiosqlite:///./treg.db}"
  [[ "$url" == sqlite* ]] || { echo "Yedekleme betiği yalnızca SQLite içindir (Postgres: pg_dump kullanın)." >&2; exit 1; }
  echo "${url#*:///}"
}

running() { curl -fsS "http://127.0.0.1:$PORT/meta" >/dev/null 2>&1; }

cmd="${1:-start}"
case "$cmd" in
  start)
    need uv "https://docs.astral.sh/uv/"; need node ">= 22.12"; need npm "Node ile gelir"
    [[ -f src/treg/web/dashboard/leads.html ]] || bash scripts/build-dashboard.sh
    uv sync --frozen
    ensure_env; load_env
    uv run --frozen python -m treg upgrade
    echo "Lead Radar: http://127.0.0.1:$PORT/leads  (Treg paneli: /app)"
    exec uv run --frozen python -m treg
    ;;
  build)
    bash scripts/build-dashboard.sh
    ;;
  backup)
    load_env
    db="$(db_file)"; stamp="$(date +%Y%m%d-%H%M%S)"; out="$BACKUP_DIR/$stamp"
    mkdir -p "$out"; chmod 700 "$BACKUP_DIR" "$out"
    # sqlite3's online backup API: consistent even while the server writes.
    uv run --frozen python - "$db" "$out/treg.db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
print("ok", dst.execute("PRAGMA integrity_check").fetchone()[0])
PY
    cp "$ENV_FILE" "$out/env"; chmod 600 "$out/env" "$out/treg.db"
    echo "Yedek: $out (DB + şifreleme anahtarı içeren env; güvenli yerde saklayın)"
    ;;
  restore)
    src="${2:?kullanım: restore <yedek-dizini>}"
    [[ -f "$src/treg.db" && -f "$src/env" ]] || { echo "$src içinde treg.db ve env bekleniyor" >&2; exit 1; }
    running && { echo "Önce sunucuyu durdurun." >&2; exit 1; }
    if [[ -f "$ENV_FILE" ]]; then load_env; db="$(db_file)"; [[ -f "$db" ]] && cp "$db" "$db.before-restore"; fi
    cp "$src/env" "$ENV_FILE"; chmod 600 "$ENV_FILE"; load_env
    db="$(db_file)"; rm -f "$db-wal" "$db-shm"; cp "$src/treg.db" "$db"
    uv run --frozen python -m treg upgrade
    echo "Geri yüklendi: $db (önceki DB varsa .before-restore olarak duruyor)"
    ;;
  *)
    echo "kullanım: $0 start|build|backup|restore <dizin>" >&2; exit 2 ;;
esac
