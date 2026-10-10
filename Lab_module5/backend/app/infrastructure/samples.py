"""Sample runs: stored completed RunViews (exported by the evaluation) served at 0 calls;
the frontend replays their transcript as an animation."""

import json
import re
from pathlib import Path
from typing import Any

from app.domain.errors import SampleNotFound

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples" / "runs"
_ID = re.compile(r"^[a-z0-9_-]{1,40}$")


class SampleStore:
    def __init__(self, root: Path = SAMPLES_DIR) -> None:
        self._root = root

    def catalog(self) -> list[dict[str, Any]]:
        index = self._root / "index.json"
        return json.loads(index.read_text()) if index.is_file() else []

    def get(self, sample_id: str) -> dict[str, Any]:
        known = {s["id"] for s in self.catalog()}
        path = self._root / f"{sample_id}.json"
        if not _ID.match(sample_id) or sample_id not in known or not path.is_file():
            raise SampleNotFound(sample_id)
        return json.loads(path.read_text()) | {"sample": True}
