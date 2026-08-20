#!/usr/bin/env sh
set -eu

source_keyfile="/run/secrets/mongodb_replica_keyfile"
target_keyfile="/tmp/mongodb-replica-keyfile"

if [ -r "$source_keyfile" ]; then
  cp "$source_keyfile" "$target_keyfile"
  chown mongodb:mongodb "$target_keyfile"
  chmod 400 "$target_keyfile"
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"

