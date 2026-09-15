"""Physical MongoDB monitored-to-evaluation state cloning with verification."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from pymongo import MongoClient

from app.mongodb.client import create_mongo_client

from app.evaluation.sandbox import EvaluationState


class MongoEvaluationStateCopier:
    """Copy an allowlisted database to a separate MongoDB target and verify its state."""

    def __init__(self, monitored_uri: str, evaluation_uri: str, database_name: str, workload_definition: object) -> None:
        self._monitored_uri = monitored_uri
        self._evaluation_uri = evaluation_uri
        self._database_name = database_name
        self._workload_fingerprint = _hash(workload_definition)

    async def copy_and_verify(self, monitored_target_id: str, evaluation_target_id: str) -> EvaluationState:
        if monitored_target_id == evaluation_target_id:
            raise ValueError("monitored and evaluation target IDs must differ")
        return await asyncio.to_thread(self._copy_and_verify)

    def _copy_and_verify(self) -> EvaluationState:
        with create_mongo_client(self._monitored_uri, local_development=True) as monitored_client, create_mongo_client(self._evaluation_uri, local_development=True) as evaluation_client:
            monitored = monitored_client[self._database_name]
            evaluation = evaluation_client[self._database_name]
            source_state = _state(monitored_client, monitored)
            _replace_database(monitored, evaluation)
            evaluation_state = _state(evaluation_client, evaluation)
            source_after = _state(monitored_client, monitored)
            if source_state["dataset_fingerprint"] != source_after["dataset_fingerprint"] or source_state["indexes_fingerprint"] != source_after["indexes_fingerprint"]:
                raise RuntimeError("monitored MongoDB changed during evaluation-state copy")
            if source_state["dataset_fingerprint"] != evaluation_state["dataset_fingerprint"]:
                raise RuntimeError("evaluation dataset fingerprint differs from monitored source")
            if source_state["indexes_fingerprint"] != evaluation_state["indexes_fingerprint"]:
                raise RuntimeError("evaluation indexes differ from monitored source")
            if source_state["mongodb_version"] != evaluation_state["mongodb_version"] or source_state["fcv"] != evaluation_state["fcv"]:
                raise RuntimeError("evaluation MongoDB environment differs from monitored source")
            free_disk_bytes = int(evaluation_client.admin.command({"serverStatus": 1}).get("fsUsedSize", 0))
            return EvaluationState(
                source_state["dataset_fingerprint"], evaluation_state["dataset_fingerprint"], source_state["topology"], evaluation_state["topology"], free_disk_bytes,
                source_state["mongodb_version"], source_state["fcv"], source_state["indexes_fingerprint"], source_state["query_settings_fingerprint"], self._workload_fingerprint,
            )


def _replace_database(source: Any, destination: Any) -> None:
    for name in destination.list_collection_names():
        destination[name].drop()
    for name in sorted(source.list_collection_names()):
        documents = list(source[name].find({}, sort=[("_id", 1)]))
        if documents:
            destination[name].insert_many(documents, ordered=True)
        for index in source[name].list_indexes():
            if index["name"] != "_id_":
                destination[name].create_index(list(index["key"].items()), name=index["name"], **{key: value for key, value in index.items() if key not in {"v", "key", "name", "ns"}})


def _state(client: MongoClient[Any], database: Any) -> dict[str, str]:
    build = client.admin.command({"buildInfo": 1})
    fcv = client.admin.command({"getParameter": 1, "featureCompatibilityVersion": 1})
    hello = client.admin.command({"hello": 1})
    collections = {
        name: list(database[name].find({}, sort=[("_id", 1)]))
        for name in sorted(database.list_collection_names())
    }
    indexes = {
        name: [{key: value for key, value in index.items() if key not in {"ns", "v"}} for index in database[name].list_indexes()]
        for name in sorted(database.list_collection_names())
    }
    return {
        "dataset_fingerprint": _hash(collections),
        "indexes_fingerprint": _hash(indexes),
        "query_settings_fingerprint": _hash([]),
        "mongodb_version": str(build.get("version", "")),
        "fcv": str(fcv.get("featureCompatibilityVersion", {}).get("version", "")),
        "topology": str(hello.get("setName", "")),
    }


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
