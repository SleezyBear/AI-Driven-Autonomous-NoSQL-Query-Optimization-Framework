#!/usr/bin/env sh
set -eu

mongo_host="$1"
replica_set="$2"

mongosh --host "$mongo_host" --quiet --eval "
  try {
    rs.status();
  } catch (error) {
    rs.initiate({_id: '$replica_set', members: [{_id: 0, host: '$mongo_host:27017'}]});
  }
"

