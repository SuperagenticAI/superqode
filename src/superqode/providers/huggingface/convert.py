"""Convert Hugging Face models to MLX format (and optionally upload).

Thin wrapper over ``mlx_lm.convert`` (text models) and ``mlx_vlm.convert``
(multimodal models): download the original HF weights, quantize to MLX, and
optionally push the result to your own HF repo. This is the "official weights ->
MLX -> your repo" path that avoids broken third-party GGUF templates and gives
you a self-controlled, Apple-Silicon-native model.

The converter is chosen from the model's ``config.json``: text models go through
mlx-lm; models with a vision/audio tower (e.g. Gemma 4 12B = ``gemma4_unified``)
go through mlx-vlm, which mlx-lm can't load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class MlxConvertUnavailable(RuntimeError):
    """Raised when the required converter (mlx-lm / mlx-vlm) isn't installed."""


def _default_out_dir(hf_path: str, q_bits: int) -> Path:
    name = hf_path.rstrip("/").split("/")[-1]
    return Path.home() / ".cache" / "superqode" / "mlx" / f"{name}-{q_bits}bit-mlx"


def _needs_vlm_converter(hf_path: str) -> bool:
    """True if mlx-vlm (not mlx-lm) should convert this model.

    Decided from the architecture/model_type *name*, not the mere presence of a
    vision_config: e.g. Gemma 4 31B carries a vision_config but loads fine as
    text via mlx-lm (``gemma4`` / Gemma4ForConditionalGeneration), whereas the
    12B is ``gemma4_unified`` / Gemma4UnifiedForConditionalGeneration and only
    mlx-vlm can load it. A runtime fallback in ``convert_to_mlx`` covers any
    model this heuristic misjudges.
    """
    try:
        import json

        from huggingface_hub import hf_hub_download

        with open(hf_hub_download(hf_path, "config.json")) as fh:
            cfg = json.load(fh)
    except Exception:  # noqa: BLE001 - network/parse issues -> assume text
        return False
    blob = (
        str(cfg.get("model_type") or "").lower()
        + " "
        + " ".join(cfg.get("architectures") or []).lower()
    )
    return "unified" in blob or "_vl" in blob or "visionlanguage" in blob


def _import_converter(use_vlm: bool):
    """Import the right MLX convert(); raise MlxConvertUnavailable if missing."""
    pkg = "mlx-vlm" if use_vlm else "mlx-lm"
    try:
        if use_vlm:
            from mlx_vlm import convert  # type: ignore
        else:
            from mlx_lm import convert  # type: ignore
        return convert
    except Exception as exc:  # noqa: BLE001
        raise MlxConvertUnavailable(
            f"{pkg} is required to convert this model. Install with: "
            f"pip install '{pkg}' (or `uv sync --extra mlx`). MLX requires Apple Silicon."
        ) from exc


def convert_to_mlx(
    hf_path: str,
    *,
    out_dir: Optional[Path] = None,
    q_bits: int = 8,
    quantize: bool = True,
    upload_repo: Optional[str] = None,
) -> Path:
    """Convert ``hf_path`` to MLX, returning the local output directory.

    Args:
        hf_path: Source HF repo id (e.g. ``google/gemma-4-31b-it``).
        out_dir: Where to write the MLX model (defaults under ~/.cache/superqode).
        q_bits: Quantization bit-width (4 or 8). Ignored when ``quantize=False``.
        quantize: Whether to quantize during conversion.
        upload_repo: If set, push the converted model to this HF repo
            (e.g. ``SuperagenticAI/gemma-4-31b-it-8bit-mlx``). Requires an HF
            token with write access.
    """
    target = Path(out_dir) if out_dir else _default_out_dir(hf_path, q_bits)
    target.parent.mkdir(parents=True, exist_ok=True)

    use_vlm = _needs_vlm_converter(hf_path)

    def _run(via_vlm: bool) -> None:
        convert = _import_converter(via_vlm)
        convert(
            hf_path,
            mlx_path=str(target),
            quantize=quantize,
            q_bits=q_bits,
            upload_repo=upload_repo,
        )

    try:
        _run(use_vlm)
    except ValueError as exc:
        # Heuristic misjudged the converter: mlx-lm raises "Model type ... not
        # supported" for multimodal arches (and vice-versa). Retry with the
        # other converter before giving up.
        if "not supported" in str(exc).lower():
            _run(not use_vlm)
        else:
            raise
    return target


__all__ = ["convert_to_mlx", "MlxConvertUnavailable"]
