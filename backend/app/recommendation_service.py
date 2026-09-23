"""Shared employee/HR recommendation service with bounded, revision-aware cache."""

from collections import OrderedDict
from copy import deepcopy
import hashlib
import os
import threading
import time

from .career import DEFAULT_AS_OF_DATE
from .recommendations import RecommendationError, recommend_employee, selector_from_environment


def data_revision(connection):
    return connection.execute("SELECT revision FROM recommendation_revision WHERE singleton = 1").fetchone()[0]


class RecommendationService:
    def __init__(self, selector_factory=None, timeout_seconds=8.0):
        self.selector_factory = selector_factory or selector_from_environment
        self.timeout_seconds = timeout_seconds
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()
        self._employee_locks = [threading.Lock() for _ in range(32)]

    def get(self, connection, employee_id, as_of_date=DEFAULT_AS_OF_DATE):
        started = time.monotonic()
        # Striped locks coalesce concurrent employee/HR requests without an
        # unbounded map of locks. Unrelated stripes can call the model in parallel.
        lock = self._employee_locks[hash(employee_id) % len(self._employee_locks)]
        if not lock.acquire(timeout=self.timeout_seconds):
            result = recommend_employee(connection, employee_id, as_of_date=as_of_date)
            result.update(cached=False, fallback_reason="AI занят другим запросом. Показаны рекомендации по правилам.")
            return result
        try:
            revision = data_revision(connection)
            config = hashlib.sha256("\0".join(os.getenv(key, "") for key in
                ("LLM_API_URL", "LLM_API_KEY", "LLM_MODEL")).encode()).hexdigest()
            key = (employee_id, revision, as_of_date, config)
            with self._cache_lock:
                entry = self._cache.get(key)
                if entry and entry[0] > time.monotonic():
                    self._cache.move_to_end(key)
                    return {**deepcopy(entry[1]), "cached": True}
            configuration_error = None
            try:
                selector = self.selector_factory()
            except RecommendationError:
                selector = None
                configuration_error = "AI настроен не полностью: задайте LLM_API_URL, LLM_API_KEY и LLM_MODEL на сервере. Показаны правила."
            result = recommend_employee(connection, employee_id, as_of_date=as_of_date,
                                        selector=selector, timeout_seconds=max(0, self.timeout_seconds - (time.monotonic() - started)))
            if configuration_error:
                result["fallback_reason"] = configuration_error
            result.update(cached=False, revision=revision)
            if data_revision(connection) != revision:
                # A completion/goal/import raced the model. Never publish or
                # cache recommendations derived from the superseded snapshot.
                return {"employee_id": employee_id, "mode": "stale", "recommendations": [],
                        "plan": None, "cached": False, "revision": revision,
                        "fallback_reason": "Данные изменились во время подбора. Обновите рекомендации."}
            ttl = 900 if result["mode"] == "llm" else 15
            with self._cache_lock:
                self._cache[key] = (time.monotonic() + ttl, deepcopy(result))
                self._cache.move_to_end(key)
                while len(self._cache) > 256:
                    self._cache.popitem(last=False)
            return result
        finally:
            lock.release()
