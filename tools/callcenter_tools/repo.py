"""Data access for the simulated enterprise systems.

Every member-owned container is partitioned by member_id, and every lookup of a
member-owned record is a point read scoped to the authenticated member's
partition. A record that belongs to someone else is therefore indistinguishable
from one that does not exist, so cross-member access is blocked structurally
rather than by after-the-fact ownership checks.
"""
from __future__ import annotations

import copy
import os
from typing import Dict, List, Optional, Protocol

# container -> (partition key field, id field)
CONTAINERS = {
    "members": ("member_id", "member_id"),
    "providers": ("provider_id", "provider_id"),
    "claims": ("member_id", "claim_id"),
    "appointments": ("member_id", "appointment_id"),
    "prescriptions": ("member_id", "prescription_id"),
}


class Repo(Protocol):
    def get(self, container: str, item_id: str, partition: str) -> Optional[dict]: ...
    def query_by_member(self, container: str, member_id: str) -> List[dict]: ...
    def upsert(self, container: str, item: dict) -> None: ...


def _clean(doc: Optional[dict]) -> Optional[dict]:
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if not k.startswith("_") and k != "id"}


def to_document(container: str, item: dict) -> dict:
    return {**item, "id": item[CONTAINERS[container][1]]}


class InMemoryRepo:
    """Test double with the same partition-scoped semantics as Cosmos."""

    def __init__(self, data: Dict[str, List[dict]]):
        self._data = {c: [copy.deepcopy(i) for i in items] for c, items in data.items()}

    def get(self, container, item_id, partition):
        pk, idf = CONTAINERS[container]
        for item in self._data.get(container, []):
            if item[idf] == item_id and item[pk] == partition:
                return copy.deepcopy(item)
        return None

    def query_by_member(self, container, member_id):
        return [copy.deepcopy(i) for i in self._data.get(container, []) if i["member_id"] == member_id]

    def upsert(self, container, item):
        pk, idf = CONTAINERS[container]
        rows = self._data.setdefault(container, [])
        for idx, existing in enumerate(rows):
            if existing[idf] == item[idf] and existing[pk] == item[pk]:
                rows[idx] = copy.deepcopy(item)
                return
        rows.append(copy.deepcopy(item))


class CosmosRepo:
    def __init__(self, endpoint: Optional[str] = None, database: Optional[str] = None):
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        endpoint = endpoint or os.environ["COSMOS_ENDPOINT"]
        database = database or os.environ.get("COSMOS_DATABASE", "callcenter")
        self._db = CosmosClient(endpoint, credential=DefaultAzureCredential()).get_database_client(database)

    def get(self, container, item_id, partition):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return _clean(self._db.get_container_client(container).read_item(item_id, partition_key=partition))
        except CosmosResourceNotFoundError:
            return None

    def query_by_member(self, container, member_id):
        rows = self._db.get_container_client(container).query_items(
            "SELECT * FROM c WHERE c.member_id = @m",
            parameters=[{"name": "@m", "value": member_id}],
            partition_key=member_id,
        )
        return [_clean(r) for r in rows]

    def upsert(self, container, item):
        self._db.get_container_client(container).upsert_item(to_document(container, item))
