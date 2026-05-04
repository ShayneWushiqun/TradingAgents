import hashlib
import json
import os
from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG

from .schemas import AnalysisRequest


CACHE_VERSION = 1


class AnalysisCache:
    def __init__(
        self,
        cache_dir: str | Path | None = None,
        fallback_cache_dir: str | Path | None = None,
    ) -> None:
        root = Path(
            cache_dir
            or os.getenv("TRADINGAGENTS_CACHE_DIR")
            or DEFAULT_CONFIG["data_cache_dir"]
        )
        self.cache_dirs = [root / "web_analysis"]
        if fallback_cache_dir is not None:
            fallback = Path(fallback_cache_dir) / "web_analysis"
            if fallback not in self.cache_dirs:
                self.cache_dirs.append(fallback)

    def key_for(self, request: AnalysisRequest) -> str:
        payload = request.model_dump(exclude={"force_refresh", "stock_name"})
        payload["analysts"] = list(payload.get("analysts") or [])
        payload["cache_version"] = CACHE_VERSION
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get(self, request: AnalysisRequest) -> dict[str, Any] | None:
        for path in self._paths_for(request):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("cache_version") == CACHE_VERSION:
                return data
        return None

    def latest(self) -> dict[str, Any] | None:
        for cache_dir in self.cache_dirs:
            path = cache_dir / "latest.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("cache_version") == CACHE_VERSION:
                return data
        return None

    def iter_completed(self, limit: int | None = None) -> list[tuple[str, dict[str, Any], float]]:
        """All cache entries ``(cache_key, payload, mtime_seconds)`` newest first.

        Used as a persistent fallback for ``AnalysisService.history(status='completed')``
        when no ``AnalysisStore`` is configured: the on-disk cache files are the only
        durable evidence that an analysis ever completed across server reloads.

        """

        seen: set[str] = set()
        rows: list[tuple[str, dict[str, Any], float]] = []
        for cache_dir in self.cache_dirs:
            if not cache_dir.exists():
                continue
            for path in cache_dir.iterdir():
                if path.suffix != ".json" or path.stem == "latest":
                    continue
                cache_key = path.stem
                if cache_key in seen:
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if data.get("cache_version") != CACHE_VERSION:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                seen.add(cache_key)
                rows.append((cache_key, data, mtime))
        rows.sort(key=lambda item: item[2], reverse=True)
        if limit is not None:
            rows = rows[: max(1, int(limit))]
        return rows

    def load_by_key(self, cache_key: str) -> dict[str, Any] | None:
        """Direct lookup by cache key (sha256 hex), bypassing request hashing."""

        key = str(cache_key or "").strip()
        if not key:
            return None
        for cache_dir in self.cache_dirs:
            path = cache_dir / f"{key}.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("cache_version") == CACHE_VERSION:
                return data
        return None

    def delete(self, request: AnalysisRequest) -> list[Path]:
        deleted: list[Path] = []
        for path in self._paths_for(request):
            if self._unlink(path):
                deleted.append(path)

            latest_path = path.parent / "latest.json"
            if self._latest_matches(latest_path, request) and self._unlink(latest_path):
                deleted.append(latest_path)
        return deleted

    def set(
        self,
        request: AnalysisRequest,
        final_state: dict[str, Any],
        decision: str,
        report_sections: dict[str, str],
    ) -> None:
        payload = {
            "cache_version": CACHE_VERSION,
            "request": request.model_dump(exclude={"force_refresh"}),
            "final_state": final_state,
            "decision": decision,
            "report_sections": report_sections,
            "final_decision": str(final_state.get("final_trade_decision", "")),
        }
        for path in self._paths_for(request):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = path.with_suffix(".tmp")
                tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                tmp_path.replace(path)
                latest_path = path.parent / "latest.json"
                latest_tmp_path = latest_path.with_suffix(".tmp")
                latest_tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                latest_tmp_path.replace(latest_path)
                return
            except OSError:
                continue

    def _paths_for(self, request: AnalysisRequest) -> list[Path]:
        filename = f"{self.key_for(request)}.json"
        return [cache_dir / filename for cache_dir in self.cache_dirs]

    def _latest_matches(self, latest_path: Path, request: AnalysisRequest) -> bool:
        if not latest_path.exists():
            return False
        try:
            data = json.loads(latest_path.read_text(encoding="utf-8"))
            cached_request = AnalysisRequest(**data["request"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return self.key_for(cached_request) == self.key_for(request)

    def _unlink(self, path: Path) -> bool:
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False
