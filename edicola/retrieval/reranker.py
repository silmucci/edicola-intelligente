"""Reranking CrossEncoder locale per esperimenti retrieval."""

from __future__ import annotations

from pathlib import Path

import numpy as np

MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
MODEL_MAX_LENGTH = 512
RERANK_CANDIDATES = 10


class LocalOnnxCrossEncoder:
    """Valuta coppie domanda-chunk con un ONNX locale, senza accesso di rete."""

    def __init__(self, model_dir: Path, *, max_length: int = MODEL_MAX_LENGTH):
        model_dir = model_dir.expanduser()
        tokenizer_path = model_dir / "tokenizer.json"
        model_path = model_dir / "onnx" / "model.onnx"
        if not tokenizer_path.is_file() or not model_path.is_file():
            raise ValueError(
                "Modello reranker locale incompleto: servono tokenizer.json "
                "e onnx/model.onnx."
            )
        if type(max_length) is not int or max_length < 2:
            raise ValueError("max_length deve essere un intero >= 2.")

        try:
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Dipendenze reranker mancanti: installare "
                "requirements-reranker.txt."
            ) from exc

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        pad_id = self._tokenizer.token_to_id("<pad>")
        if pad_id is None:
            raise ValueError("Tokenizer reranker senza token di padding.")
        self._tokenizer.enable_truncation(max_length=max_length)
        self._tokenizer.enable_padding(pad_id=pad_id, pad_token="<pad>")
        self._session = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._max_length = max_length

    def predict_scores(
        self, question: str, candidates: list[dict]
    ) -> list[float]:
        if not question.strip():
            raise ValueError("La domanda reranker non può essere vuota.")
        if not candidates:
            return []

        pairs = [(question, candidate["text"]) for candidate in candidates]
        encodings = self._tokenizer.encode_batch(pairs)
        arrays = {
            "input_ids": np.asarray(
                [encoding.ids for encoding in encodings], dtype=np.int64
            ),
            "attention_mask": np.asarray(
                [encoding.attention_mask for encoding in encodings],
                dtype=np.int64,
            ),
            "token_type_ids": np.asarray(
                [encoding.type_ids for encoding in encodings], dtype=np.int64
            ),
        }

        feeds = {}
        for model_input in self._session.get_inputs():
            value = arrays.get(model_input.name)
            if value is None:
                raise ValueError(
                    "Il modello ONNX richiede un input non supportato."
                )
            if model_input.type == "tensor(int32)":
                value = value.astype(np.int32)
            elif model_input.type != "tensor(int64)":
                raise ValueError("Tipo input ONNX non supportato.")
            feeds[model_input.name] = value

        outputs = self._session.run(None, feeds)
        if not outputs:
            raise ValueError("Il modello ONNX non ha restituito punteggi.")
        logits = np.asarray(outputs[0], dtype=float)
        if logits.size != len(candidates) or not np.isfinite(logits).all():
            raise ValueError("Punteggi reranker non validi.")
        return [float(score) for score in logits.reshape(-1)]
