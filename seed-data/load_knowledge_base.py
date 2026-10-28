"""Create the Foundry IQ knowledge bases (Azure AI Search) and load the KB documents.

For each domain folder in seed-data/kb-documents/ this creates:
  index `kb-<domain>` (one chunk per `##` section) -> knowledge source `ks-<domain>`
  -> knowledge base `kb-<domain>`

Idempotent (create-or-update). Uses Entra auth; the caller needs Search Service
Contributor + Search Index Data Contributor (granted by infra/search.bicep).

Usage: python seed-data/load_knowledge_base.py https://<service>.search.windows.net
"""
import re
import sys
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential

API = "2026-04-01"
DOCS = Path(__file__).parent / "kb-documents"


def chunks(path: Path):
    text = path.read_text()
    title = re.match(r"#\s+(.+)", text).group(1).strip()
    for i, part in enumerate(re.split(r"\n(?=## )", text)[1:] or [text]):
        heading = part.splitlines()[0].lstrip("# ").strip()
        yield {
            "id": f"{path.stem}-{i}",
            "title": title,
            "section": heading,
            "source": path.name,
            "content": part.strip(),
        }


def main(endpoint: str):
    token = DefaultAzureCredential().get_token("https://search.azure.com/.default").token
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    def put(path, body):
        r = s.put(f"{endpoint}/{path}?api-version={API}", json=body)
        if not r.ok:
            sys.exit(f"PUT {path} -> {r.status_code}: {r.text}")

    for domain_dir in sorted(p for p in DOCS.iterdir() if p.is_dir()):
        d = domain_dir.name
        index = f"kb-{d}"
        put(f"indexes/{index}", {
            "name": index,
            "fields": [
                {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "title", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "section", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "source", "type": "Edm.String", "filterable": True, "retrievable": True},
                {"name": "content", "type": "Edm.String", "searchable": True, "retrievable": True},
            ],
            "semantic": {
                "defaultConfiguration": "default",
                "configurations": [{
                    "name": "default",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "title"},
                        "prioritizedContentFields": [{"fieldName": "content"}],
                    },
                }],
            },
        })
        docs = [c for f in sorted(domain_dir.glob("*.md")) for c in chunks(f)]
        r = s.post(f"{endpoint}/indexes/{index}/docs/index?api-version={API}",
                   json={"value": [{"@search.action": "mergeOrUpload", **c} for c in docs]})
        if not r.ok:
            sys.exit(f"index docs {index} -> {r.status_code}: {r.text}")
        put(f"knowledgesources/ks-{d}", {
            "name": f"ks-{d}",
            "kind": "searchIndex",
            "description": f"{d} policy and FAQ documents",
            "searchIndexParameters": {
                "searchIndexName": index,
                "sourceDataFields": [{"name": "title"}, {"name": "section"}, {"name": "source"}, {"name": "content"}],
                "searchFields": [{"name": "content"}, {"name": "title"}, {"name": "section"}],
                "semanticConfigurationName": "default",
            },
        })
        put(f"knowledgebases/kb-{d}", {
            "name": f"kb-{d}",
            "description": f"Grounding documents for the {d} specialist",
            "knowledgeSources": [{"name": f"ks-{d}"}],
        })
        print(f"{d}: {len(docs)} chunks -> kb-{d}")


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"))
