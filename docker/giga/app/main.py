"""OpenAI-compatible embeddings for ai-sage/Giga-Embeddings-instruct."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("giga-embeddings")

MODEL_ID = os.environ.get("MODEL_ID", "ai-sage/Giga-Embeddings-instruct")
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()

_model = None
_model_id_loaded = MODEL_ID
_load_error: str | None = None
_ready = threading.Event()


def _load_model() -> None:
    global _model, _model_id_loaded, _load_error
    try:
        if HF_TOKEN:
            os.environ["HF_TOKEN"] = HF_TOKEN
            os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN

        from sentence_transformers import SentenceTransformer

        if not torch.cuda.is_available():
            log.warning("CUDA is not available; loading %s on CPU (very slow)", MODEL_ID)

        model_kwargs: dict[str, Any] = {
            "torch_dtype": torch.bfloat16,
            "trust_remote_code": True,
        }
        try:
            import flash_attn  # noqa: F401

            model_kwargs["attn_implementation"] = "flash_attention_2"
            log.info("flash_attn is available; using flash_attention_2")
        except Exception:
            log.info("flash_attn not available; using default attention")

        try:
            model = SentenceTransformer(
                MODEL_ID,
                trust_remote_code=True,
                model_kwargs=model_kwargs,
                config_kwargs={"trust_remote_code": True},
            )
        except Exception as exc:
            if "attn_implementation" in model_kwargs:
                log.warning("flash_attention_2 failed (%s); retrying without it", exc)
                model_kwargs.pop("attn_implementation", None)
                model = SentenceTransformer(
                    MODEL_ID,
                    trust_remote_code=True,
                    model_kwargs=model_kwargs,
                    config_kwargs={"trust_remote_code": True},
                )
            else:
                raise

        model.max_seq_length = 4096
        _model = model
        _model_id_loaded = MODEL_ID
        log.info("Model %s loaded (dim=%s)", MODEL_ID, model.get_sentence_embedding_dimension())
    except Exception:
        _load_error = "model load failed"
        log.exception("Failed to load embedding model")
    finally:
        _ready.set()


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str = "float"


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: list[float]
    index: int


class EmbeddingUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: EmbeddingUsage = Field(default_factory=EmbeddingUsage)


app = FastAPI(title="Giga Embeddings", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_load_model, name="giga-load", daemon=True).start()


@app.get("/health")
def health() -> dict[str, str]:
    if _model is None:
        if _ready.is_set() and _load_error:
            raise HTTPException(status_code=503, detail="model failed to load")
        raise HTTPException(status_code=503, detail="model loading")
    return {"status": "ok", "model": _model_id_loaded}


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID.split("/")[-1],
                "object": "model",
                "owned_by": "ai-sage",
                "root": MODEL_ID,
            }
        ],
    }


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def create_embeddings(req: EmbeddingRequest) -> EmbeddingResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="model not ready")
    if req.encoding_format != "float":
        raise HTTPException(status_code=400, detail="only encoding_format=float is supported")

    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    if not texts:
        raise HTTPException(status_code=400, detail="input is empty")
    if any(not isinstance(t, str) for t in texts):
        raise HTTPException(status_code=400, detail="input must be a string or list of strings")

    vectors: list[list[float]] = []
    batch_size = 8
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            emb = _model.encode(
                batch,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors.extend(row.astype(float).tolist() for row in emb)

    model_name = req.model or MODEL_ID.split("/")[-1]
    return EmbeddingResponse(
        data=[EmbeddingData(embedding=vec, index=i) for i, vec in enumerate(vectors)],
        model=model_name,
        usage=EmbeddingUsage(prompt_tokens=0, total_tokens=0),
    )
