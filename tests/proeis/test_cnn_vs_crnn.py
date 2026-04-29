"""Train quick local CAPTCHA experiments: fixed-position CNN vs CRNN/CTC.

This is an isolated lab script. It does not touch the production automation and
does not call paid captcha services. Labels are loaded from files previously
saved in the test folders.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "tests" / "proeis" / "cnn_crnn_benchmark"
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_CAPTCHA_LEN = 6
PAD_IDX = len(CHARS)
IMG_W = 160
IMG_H = 60
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str
    source: str


def label_from_name(path: Path) -> str | None:
    stem = path.stem.upper()
    suffix = stem.rsplit("_", 1)[-1]
    if re.fullmatch(r"[A-Z0-9]{5,6}", suffix):
        return suffix
    return None


def load_samples() -> list[Sample]:
    samples: list[Sample] = []
    labeled_dirs = [
        (ROOT / "tests" / "saved_captcha_2captcha_labels", "2captcha_file_label"),
        (ROOT / "tests" / "proeis" / "validated_2captcha" / "accepted", "proeis_validated"),
        (ROOT / "tests" / "proeis" / "pdf_2captcha_labeled", "2captcha_pdf_label"),
    ]
    for folder, source in labeled_dirs:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.png")):
            label = label_from_name(path)
            if label and 5 <= len(label) <= MAX_CAPTCHA_LEN and all(c in CHARS for c in label):
                samples.append(Sample(path=path, label=label, source=source))
    unique: dict[Path, Sample] = {s.path: s for s in samples}
    return list(unique.values())


def read_image(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L")
    arr = np.array(img)
    arr = cv2.resize(arr, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
    arr = cv2.equalizeHist(arr)
    arr = 255 - arr
    arr = arr.astype(np.float32) / 255.0
    return arr


def augment(img: np.ndarray) -> np.ndarray:
    h, w = img.shape
    angle = random.uniform(-4.0, 4.0)
    scale = random.uniform(0.94, 1.06)
    tx = random.uniform(-4, 4)
    ty = random.uniform(-3, 3)
    mat = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    mat[:, 2] += (tx, ty)
    out = cv2.warpAffine(img, mat, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if random.random() < 0.45:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    noise = np.random.normal(0, random.uniform(0.0, 0.035), out.shape).astype(np.float32)
    out = np.clip(out + noise, 0.0, 1.0)
    return out


class CaptchaDataset(Dataset):
    def __init__(self, samples: list[Sample], repeats: int, train: bool):
        self.items = samples
        self.repeats = repeats
        self.train = train
        self.char_to_idx = {c: i for i, c in enumerate(CHARS)}

    def __len__(self) -> int:
        return len(self.items) * self.repeats

    def __getitem__(self, idx: int):
        sample = self.items[idx % len(self.items)]
        img = read_image(sample.path)
        if self.train:
            img = augment(img)
        x = torch.from_numpy(img[None, :, :])
        encoded = [self.char_to_idx[c] for c in sample.label]
        padded = encoded + [PAD_IDX] * (MAX_CAPTCHA_LEN - len(encoded))
        y = torch.tensor(padded, dtype=torch.long)
        return x, y, len(encoded), sample.label


class PositionCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 10)),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128 * 4 * 10, 384),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(384, MAX_CAPTCHA_LEN * (len(CHARS) + 1)),
        )

    def forward(self, x):
        y = self.head(self.features(x))
        return y.view(-1, MAX_CAPTCHA_LEN, len(CHARS) + 1)


class CRNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d((2, 2)),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d((2, 2)),
            nn.Conv2d(64, 96, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d((2, 1)),
        )
        self.rnn = nn.GRU(96 * 7, 128, num_layers=2, bidirectional=True, batch_first=True)
        self.classifier = nn.Linear(256, len(CHARS) + 1)

    def forward(self, x):
        feat = self.cnn(x)
        b, c, h, w = feat.shape
        seq = feat.permute(0, 3, 1, 2).contiguous().view(b, w, c * h)
        seq, _ = self.rnn(seq)
        return self.classifier(seq).log_softmax(2)


def decode_position(logits: torch.Tensor) -> list[str]:
    idx = logits.argmax(dim=2).detach().cpu().numpy()
    decoded = []
    for row in idx:
        chars = []
        for i in row:
            if i == PAD_IDX:
                continue
            chars.append(CHARS[i])
        decoded.append("".join(chars))
    return decoded


def decode_ctc(log_probs: torch.Tensor) -> list[str]:
    blank = len(CHARS)
    raw = log_probs.argmax(dim=2).detach().cpu().numpy()
    decoded: list[str] = []
    for row in raw:
        prev = blank
        text = []
        for i in row:
            if i != blank and i != prev:
                text.append(CHARS[i])
            prev = i
        decoded.append("".join(text)[:MAX_CAPTCHA_LEN])
    return decoded


def split_samples(samples: list[Sample]) -> tuple[list[Sample], list[Sample]]:
    validated = [s for s in samples if s.source == "proeis_validated"]
    others = [s for s in samples if s.source != "proeis_validated"]
    if len(validated) >= 3 and len(others) >= 6:
        return others, validated
    random.shuffle(samples)
    test_count = max(1, round(len(samples) * 0.25))
    return samples[test_count:], samples[:test_count]


def evaluate(model: nn.Module, loader: DataLoader, kind: str) -> dict:
    model.eval()
    start = time.perf_counter()
    rows = []
    with torch.no_grad():
        for x, _, _, labels in loader:
            x = x.to(DEVICE)
            out = model(x)
            preds = decode_position(out) if kind == "cnn" else decode_ctc(out)
            for label, pred in zip(labels, preds):
                rows.append(
                    {
                        "expected": label,
                        "predicted": pred,
                        "exact": pred == label,
                        "char_hits": sum(a == b for a, b in zip(pred.ljust(MAX_CAPTCHA_LEN), label)),
                        "expected_len": len(label),
                    }
                )
    elapsed_ms = (time.perf_counter() - start) * 1000
    total = max(1, len(rows))
    return {
        "exact_accuracy": sum(r["exact"] for r in rows) / total,
        "char_accuracy": sum(r["char_hits"] for r in rows) / max(1, sum(r["expected_len"] for r in rows)),
        "avg_predict_ms": elapsed_ms / total,
        "rows": rows,
    }


def train_cnn(train: list[Sample], test: list[Sample], epochs: int) -> dict:
    model = PositionCNN().to(DEVICE)
    loader = DataLoader(CaptchaDataset(train, repeats=80, train=True), batch_size=16, shuffle=True)
    test_loader = DataLoader(CaptchaDataset(test, repeats=1, train=False), batch_size=8)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss()
    losses = []
    for _ in range(epochs):
        model.train()
        total = 0.0
        for x, y, _, _ in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            opt.zero_grad()
            logits = model(x)
            loss = sum(loss_fn(logits[:, i, :], y[:, i]) for i in range(MAX_CAPTCHA_LEN)) / MAX_CAPTCHA_LEN
            loss.backward()
            opt.step()
            total += float(loss.item())
        losses.append(total / max(1, len(loader)))
    result = evaluate(model, test_loader, "cnn")
    result["losses"] = losses
    return result


def train_crnn(train: list[Sample], test: list[Sample], epochs: int) -> dict:
    model = CRNN().to(DEVICE)
    loader = DataLoader(CaptchaDataset(train, repeats=80, train=True), batch_size=16, shuffle=True)
    test_loader = DataLoader(CaptchaDataset(test, repeats=1, train=False), batch_size=8)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CTCLoss(blank=len(CHARS), zero_infinity=True)
    losses = []
    for _ in range(epochs):
        model.train()
        total = 0.0
        for x, y, lengths, _ in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            opt.zero_grad()
            log_probs = model(x).permute(1, 0, 2)
            input_lengths = torch.full((x.size(0),), log_probs.size(0), dtype=torch.long)
            current_target_lengths = lengths.long()
            targets = torch.cat([row[: int(length)] for row, length in zip(y.cpu(), current_target_lengths)])
            loss = loss_fn(log_probs, targets.to(DEVICE), input_lengths, current_target_lengths)
            loss.backward()
            opt.step()
            total += float(loss.item())
        losses.append(total / max(1, len(loader)))
    result = evaluate(model, test_loader, "crnn")
    result["losses"] = losses
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=8)
    args = parser.parse_args()
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)

    samples = load_samples()
    if len(samples) < 8:
        raise SystemExit(f"Poucos samples rotulados: {len(samples)}")
    train, test = split_samples(samples)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    cnn = train_cnn(train, test, args.epochs)
    crnn = train_crnn(train, test, args.epochs)
    report = {
        "device": str(DEVICE),
        "chars": CHARS,
        "sample_count": len(samples),
        "train": [{"file": str(s.path), "label": s.label, "source": s.source} for s in train],
        "test": [{"file": str(s.path), "label": s.label, "source": s.source} for s in test],
        "epochs": args.epochs,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "cnn_position": cnn,
        "crnn_ctc": crnn,
    }
    out = OUT_DIR / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "device": str(DEVICE),
        "sample_count": len(samples),
        "train_count": len(train),
        "test_count": len(test),
        "cnn": {k: cnn[k] for k in ("exact_accuracy", "char_accuracy", "avg_predict_ms")},
        "crnn": {k: crnn[k] for k in ("exact_accuracy", "char_accuracy", "avg_predict_ms")},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
