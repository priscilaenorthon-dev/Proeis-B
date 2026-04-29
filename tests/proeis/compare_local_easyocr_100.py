from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import easyocr
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
OUT_DIR = Path(__file__).resolve().parent / "local_easyocr_compare"
LOCAL_MODEL_PATH = TESTS_DIR / "saved_captcha_ocr_model.pkl"

sys.path.insert(0, str(TESTS_DIR))
from captcha_ocr_train import char_crop, featurize_char  # noqa: E402
from easyocr_captcha_eval import preprocess, read_easyocr  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_refresh_images import new_session, refresh_captcha, select_id_access, extract_captcha  # noqa: E402


@dataclass(frozen=True)
class CompareRow:
    index: int
    file: str
    local: str
    local_ms: int
    easyocr: str
    easyocr_ms: int
    easyocr_variant: str
    local_valid: bool
    easyocr_valid: bool
    agree: bool


def normalize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def valid_shape(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{6}", normalize(value)))


def predict_local(model, image_path: Path) -> tuple[str, int]:
    image = Image.open(image_path).convert("RGB")
    start = time.perf_counter()
    pred = "".join(model.predict([featurize_char(char_crop(image, pos))])[0] for pos in range(6))
    return normalize(pred), int((time.perf_counter() - start) * 1000)


def predict_easyocr(reader, image_path: Path, variants: list[str]) -> tuple[str, int, str]:
    best_variant = ""
    best_text = ""
    total_ms = 0
    for variant in variants:
        image = preprocess(image_path, variant)
        start = time.perf_counter()
        pred = normalize(read_easyocr(reader, image, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
        total_ms += int((time.perf_counter() - start) * 1000)
        if valid_shape(pred):
            return pred, total_ms, variant
        if len(pred) > len(best_text):
            best_text = pred
            best_variant = variant
    return best_text, total_ms, best_variant or variants[0]


def write_report(out_dir: Path, rows: list[CompareRow], completed: bool) -> None:
    summary = {
        "count": len(rows),
        "completed": completed,
        "local_valid": sum(row.local_valid for row in rows),
        "easyocr_valid": sum(row.easyocr_valid for row in rows),
        "agree": sum(row.agree for row in rows),
        "avg_local_ms": round(sum(row.local_ms for row in rows) / len(rows), 1) if rows else 0,
        "avg_easyocr_ms": round(sum(row.easyocr_ms for row in rows) / len(rows), 1) if rows else 0,
    }
    report = {"summary": summary, "rows": [asdict(row) for row in rows]}
    (out_dir / "comparison_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara OCR local e EasyOCR em 100 captchas novos do PROEIS.")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--variants", default="gray,clahe,otsu,adaptive,dark_mask")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = out_dir / "images"
    image_dir.mkdir(exist_ok=True)

    with LOCAL_MODEL_PATH.open("rb") as fh:
        local_model = pickle.load(fh)["model"]

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    variants = [item.strip() for item in args.variants.split(",") if item.strip()]

    session = new_session()
    soup = select_id_access(session)
    rows: list[CompareRow] = []

    try:
        for index in range(1, args.count + 1):
            if index > 1:
                soup = refresh_captcha(session, soup)
            image = extract_captcha(str(soup))
            image_path = image_dir / f"captcha_{index:03d}.png"
            image_path.write_bytes(image)

            local_text, local_ms = predict_local(local_model, image_path)
            easy_text, easy_ms, easy_variant = predict_easyocr(reader, image_path, variants)
            row = CompareRow(
                index=index,
                file=f"images/{image_path.name}",
                local=local_text,
                local_ms=local_ms,
                easyocr=easy_text,
                easyocr_ms=easy_ms,
                easyocr_variant=easy_variant,
                local_valid=valid_shape(local_text),
                easyocr_valid=valid_shape(easy_text),
                agree=local_text == easy_text and bool(local_text),
            )
            rows.append(row)
            write_report(out_dir, rows, completed=False)
            print(
                f"{index:03d}/{args.count}: local={local_text or '-'} ({local_ms}ms) "
                f"easy={easy_text or '-'}[{easy_variant}] ({easy_ms}ms) agree={row.agree}"
            )
            if args.delay > 0 and index < args.count:
                time.sleep(args.delay)
    finally:
        write_report(out_dir, rows, completed=len(rows) >= args.count)

    print(f"Relatorio: {out_dir / 'comparison_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
