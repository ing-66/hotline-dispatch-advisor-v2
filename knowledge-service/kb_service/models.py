from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np


class Models:
    def __init__(self, cfg: dict):
        cache = cfg["model_cache"]
        Path(cache).mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = cache
        os.environ["TRANSFORMERS_CACHE"] = str(Path(cache) / "transformers")
        # The model is fully cached locally. Avoid slow network probes on every
        # service restart and keep retrieval available without Internet access.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        self.cfg = cfg
        self._embedder = None
        self._reranker = None
        self.lock = threading.Lock()
        self._embedding_cache: OrderedDict[tuple[str, ...], np.ndarray] = OrderedDict()
        self._embedding_cache_limit = int(cfg.get("embedding_cache_entries", 128))

    @property
    def embedder(self):
        if self._embedder is None:
            with self.lock:
                if self._embedder is None:
                    from sentence_transformers import SentenceTransformer
                    self._embedder = SentenceTransformer(self.cfg["dense_model"], cache_folder=self.cfg["model_cache"], device="cpu")
        return self._embedder

    @property
    def reranker(self):
        if not self.cfg.get("enable_reranker", True):
            return None
        if self._reranker is None:
            with self.lock:
                if self._reranker is None:
                    from sentence_transformers import CrossEncoder
                    self._reranker = CrossEncoder(self.cfg["reranker_model"], cache_folder=self.cfg["model_cache"], device="cpu")
        return self._reranker

    def embed(self, texts: list[str]):
        key = tuple(texts)
        embedder = self.embedder
        # A single hotline request searches several knowledge categories with
        # the same expanded queries. Serializing a cache miss prevents those
        # concurrent category requests from encoding the same text repeatedly.
        with self.lock:
            cached = self._embedding_cache.get(key)
            if cached is not None:
                self._embedding_cache.move_to_end(key)
                return cached.copy()
            vectors = embedder.encode(
                texts,
                normalize_embeddings=True,
                batch_size=int(self.cfg.get("embed_batch_size", 4)),
                show_progress_bar=False,
            )
            self._embedding_cache[key] = vectors.copy()
            self._embedding_cache.move_to_end(key)
            while len(self._embedding_cache) > self._embedding_cache_limit:
                self._embedding_cache.popitem(last=False)
            return vectors
