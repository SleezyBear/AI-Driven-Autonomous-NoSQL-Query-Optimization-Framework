#!/usr/bin/env python3
"""Prove the MongoDB executor credential cannot modify application documents."""

from __future__ import annotations

import sys
import os
from collections.abc import Callable

from pymongo import MongoClient
from pymongo.errors import OperationFailure


EXECUTOR_URI = os.environ.get(
    "MONGODB_EXECUTOR_URI",
    "mongodb://optimizer_executor:executor_dev_only@127.0.0.1:27017/commerce?"
    "authSource=admin&directConnection=true",
)


def must_be_denied(operation_name: str, operation: Callable[[], object]) -> None:
    """Assert that an operation fails with MongoDB authorization failure."""
    try:
        operation()
    except OperationFailure:
        print(f"{operation_name}: DENIED")
        return
    raise AssertionError(f"{operation_name}: executor credential was incorrectly allowed")


def main() -> int:
    """Run mandatory negative permission checks using only the executor credential."""
    client = MongoClient(EXECUTOR_URI, serverSelectionTimeoutMS=5_000)
    database = client.get_database("commerce")
    collection = database.get_collection("permission_probe")
    try:
        database.list_collection_names()
        collection.list_indexes().to_list()
        client.get_database("admin").aggregate([{"$querySettings": {}}]).to_list()
        print("query settings metadata: ALLOWED")
        must_be_denied("insert", lambda: collection.insert_one({"forbidden": True}))
        must_be_denied("update", lambda: collection.update_one({}, {"$set": {"forbidden": True}}))
        must_be_denied("replace", lambda: collection.replace_one({}, {"forbidden": True}, upsert=True))
        must_be_denied("delete", lambda: collection.delete_one({}))
        must_be_denied("drop collection", lambda: database.drop_collection("permission_probe"))
        must_be_denied("drop database", lambda: client.drop_database("commerce"))
    finally:
        client.close()
    print("MongoDB executor permission boundary: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OperationFailure) as error:
        print(f"MongoDB executor permission boundary: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
