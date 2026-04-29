"""Run the local OCR experiments against one captcha image."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import re
import sys
import time
from pathlib import Path

import cv2
import easyocr
import torch


ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao consegui carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def normalize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def run_saved_local(image_path: Path) -> dict:
    mod = load_module(TESTS_DIR / "captcha_ocr_train.py", "captcha_ocr_train")
    model_path = TESTS_DIR / "saved_captcha_ocr_model.pkl"
    start = time.perf_counter()
    pred = mod.predict(image_path, model_path)
    return {"method": "ocr_local_simples_saved_linear_svc", "prediction": normalize(pred), "ms": round((time.perf_counter() - start) * 1000, 2)}


def run_easyocr(image_path: Path) -> list[dict]:
    mod = load_module(TESTS_DIR / "easyocr_captcha_eval.py", "easyocr_captcha_eval")
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    rows = []
    for variant in ["gray", "clahe", "otsu", "adaptive", "dark_mask"]:
        image = mod.preprocess(image_path, variant)
        start = time.perf_counter()
        pred = mod.read_easyocr(reader, image, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        rows.append({"method": f"easyocr_opencv_{variant}", "prediction": normalize(pred), "ms": round((time.perf_counter() - start) * 1000, 2)})
    return rows


def train_quick_torch_models(epochs: int):
    mod = load_module(TESTS_DIR / "proeis" / "test_cnn_vs_crnn.py", "test_cnn_vs_crnn")
    samples = mod.load_samples()
    train, _ = mod.split_samples(samples)

    cnn = mod.PositionCNN().to(mod.DEVICE)
    loader = torch.utils.data.DataLoader(mod.CaptchaDataset(train, repeats=45, train=True), batch_size=16, shuffle=True)
    opt = torch.optim.Adam(cnn.parameters(), lr=1e-3)
    loss_fn = torch.nn.CrossEntropyLoss()
    for _ in range(epochs):
        cnn.train()
        for x, y, _, _ in loader:
            x, y = x.to(mod.DEVICE), y.to(mod.DEVICE)
            opt.zero_grad()
            logits = cnn(x)
            loss = sum(loss_fn(logits[:, i, :], y[:, i]) for i in range(mod.MAX_CAPTCHA_LEN)) / mod.MAX_CAPTCHA_LEN
            loss.backward()
            opt.step()

    crnn = mod.CRNN().to(mod.DEVICE)
    loader = torch.utils.data.DataLoader(mod.CaptchaDataset(train, repeats=45, train=True), batch_size=16, shuffle=True)
    opt = torch.optim.Adam(crnn.parameters(), lr=1e-3)
    ctc = torch.nn.CTCLoss(blank=len(mod.CHARS), zero_infinity=True)
    for _ in range(epochs):
        crnn.train()
        for x, y, lengths, _ in loader:
            x, y = x.to(mod.DEVICE), y.to(mod.DEVICE)
            opt.zero_grad()
            log_probs = crnn(x).permute(1, 0, 2)
            input_lengths = torch.full((x.size(0),), log_probs.size(0), dtype=torch.long)
            target_lengths = lengths.long()
            targets = torch.cat([row[: int(length)] for row, length in zip(y.cpu(), target_lengths)])
            loss = ctc(log_probs, targets.to(mod.DEVICE), input_lengths, target_lengths)
            loss.backward()
            opt.step()
    return mod, cnn, crnn


def run_torch_models(image_path: Path, epochs: int) -> list[dict]:
    mod, cnn, crnn = train_quick_torch_models(epochs)
    arr = mod.read_image(image_path)
    x = torch.from_numpy(arr[None, None, :, :]).to(mod.DEVICE)
    rows = []
    cnn.eval()
    with torch.no_grad():
        start = time.perf_counter()
        pred = mod.decode_position(cnn(x))[0]
        rows.append({"method": f"cnn_position_torch_ep{epochs}", "prediction": normalize(pred), "ms": round((time.perf_counter() - start) * 1000, 2)})
    crnn.eval()
    with torch.no_grad():
        start = time.perf_counter()
        pred = mod.decode_ctc(crnn(x))[0]
        rows.append({"method": f"crnn_ctc_torch_ep{epochs}", "prediction": normalize(pred), "ms": round((time.perf_counter() - start) * 1000, 2)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+")
    parser.add_argument("--label", action="append", default=[], help="Label na mesma ordem das imagens.")
    parser.add_argument("--torch-epochs", type=int, default=4)
    args = parser.parse_args()

    image_paths = [Path(item).resolve() for item in args.images]
    labels = [normalize(item) for item in args.label]
    while len(labels) < len(image_paths):
        labels.append("")

    torch_bundle = train_quick_torch_models(args.torch_epochs)
    report_rows = []
    for image_path, label in zip(image_paths, labels):
        rows = [run_saved_local(image_path)]
        rows.extend(run_easyocr(image_path))

        mod, cnn, crnn = torch_bundle
        arr = mod.read_image(image_path)
        x = torch.from_numpy(arr[None, None, :, :]).to(mod.DEVICE)
        cnn.eval()
        with torch.no_grad():
            start = time.perf_counter()
            pred = mod.decode_position(cnn(x))[0]
            rows.append({"method": f"cnn_position_torch_ep{args.torch_epochs}", "prediction": normalize(pred), "ms": round((time.perf_counter() - start) * 1000, 2)})
        crnn.eval()
        with torch.no_grad():
            start = time.perf_counter()
            pred = mod.decode_ctc(crnn(x))[0]
            rows.append({"method": f"crnn_ctc_torch_ep{args.torch_epochs}", "prediction": normalize(pred), "ms": round((time.perf_counter() - start) * 1000, 2)})

        if label:
            for row in rows:
                row["exact"] = row["prediction"] == label
                row["char_hits"] = sum(a == b for a, b in zip(row["prediction"].ljust(len(label)), label))
        report_rows.append({"image": str(image_path), "label": label or None, "rows": rows})

    report = {"items": report_rows}
    out = TESTS_DIR / "proeis" / "single_image_ocr_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
