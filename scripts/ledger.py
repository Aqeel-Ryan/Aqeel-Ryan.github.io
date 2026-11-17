"""published.json ledger: slug -> platform -> {id, url, published_at}."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        if path.exists() and path.read_text(encoding="utf-8").strip():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} must contain a JSON object")
            self.data = loaded

    def has(self, slug: str, platform: str) -> bool:
        return platform in self.data.get(slug, {})

    def get(self, slug: str, platform: str) -> dict[str, Any] | None:
        return self.data.get(slug, {}).get(platform)

    def record(self, slug: str, platform: str, *, id: str, url: str | None) -> None:
        self.data.setdefault(slug, {})[platform] = {
            "id": str(id),
            "url": url,
            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.save()

    def save(self) -> None:
        """Atomic write so an interrupted run never leaves a half-written ledger."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, sort_keys=True, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
