from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import easyocr
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "tests" / "saved_captcha_2captcha_labels"


@dataclass(frozen=True)
class EvalRow:
    file: str
    label: str
    variant: str
    prediction: str
    ms: int
    exact: bool
    valid_shape: bool


def normalize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def valid_shape(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{6}", normalize(value)))


def preprocess(path: Path, variant: str) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Nao consegui abrir {path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if variant == "gray":
        out = gray
    elif variant == "clahe":
        out = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    elif variant == "otsu":
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        _, out = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif variant == "adaptive":
        out = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
    elif variant == "dark_mask":
        # Remove parte dos pontos coloridos claros e mantem linhas/caracteres escuros.
        _, out = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY)
    else:
        raise ValueError(f"Variant desconhecida: {variant}")

    scale = 2
    return cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def read_easyocr(reader, image: np.ndarray, allowlist: str) -> str:
    results = reader.readtext(
        image,
        detail=0,
        paragraph=False,
        allowlist=allowlist,
        decoder="greedy",
        batch_size=1,
    )
    return normalize("".join(results))


def evaluate(data_dir: Path, variants: list[str], limit: int = 0) -> dict:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    samples = [s for s in manifest.get("samples", []) if s.get("valid_shape")]
    if limit:
        samples = samples[:limit]

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    rows: list[EvalRow] = []
    allowlist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    for sample in samples:
        path = data_dir / sample["file"]
        for variant in variants:
            image = preprocess(path, variant)
            start = time.perf_counter()
            pred = read_easyocr(reader, image, allowlist)
            ms = int((time.perf_counter() - start) * 1000)
            label = sample["label"].upper()
            row = EvalRow(
                file=sample["file"],
                label=label,
                variant=variant,
                prediction=pred,
                ms=ms,
                exact=pred == label,
                valid_shape=valid_shape(pred),
            )
            rows.append(row)
            print(f"{variant:9s} {sample['file']}: pred={pred or '-':8s} label={label} exact={row.exact} {ms}ms")

    summary = {}
    for variant in variants:
        subset = [row for row in rows if row.variant == variant]
        summary[variant] = {
            "count": len(subset),
            "exact": sum(row.exact for row in subset),
            "valid_shape": sum(row.valid_shape for row in subset),
            "avg_ms": round(sum(row.ms for row in subset) / len(subset), 1) if subset else 0,
        }

    report = {"summary": summary, "rows": [asdict(row) for row in rows]}
    (data_dir / "easyocr_eval_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia EasyOCR em captchas salvos.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--variants", default="gray,clahe,otsu,adaptive,dark_mask")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    report = evaluate(Path(args.data_dir), [item.strip() for item in args.variants.split(",") if item.strip()], args.limit)
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
