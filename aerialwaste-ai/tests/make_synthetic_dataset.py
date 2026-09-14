"""
make_synthetic_dataset.py
===========================

สร้างชุดข้อมูลปลอมขนาดเล็ก (random noise images) ที่มีโครงสร้างเหมือน AerialWaste
(training.json / testing.json / images/) ใช้สำหรับทดสอบว่าโค้ด train/infer
รันได้จริงโดยไม่มี error ทาง syntax/logic — ก่อนที่จะมีข้อมูลจริงจาก Zenodo

รัน:
    python tests/make_synthetic_dataset.py --out ./tests/_synthetic_data
"""

import argparse
import json
import random
from pathlib import Path

from PIL import Image


def make_split(images_dir, n_images, prefix, seed):
    random.seed(seed)
    records = []
    for i in range(n_images):
        file_name = f"{prefix}_{i:03d}.jpg"
        img = Image.new(
            "RGB", (64, 64),
            color=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)),
        )
        img.save(images_dir / file_name)
        records.append({
            "id": i,
            "file_name": file_name,
            "is_candidate_location": random.randint(0, 1),
            "width": 64,
            "height": 64,
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "_synthetic_data")
    parser.add_argument("--n-train", type=int, default=12)
    parser.add_argument("--n-test", type=int, default=6)
    args = parser.parse_args()

    images_dir = args.out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    train_records = make_split(images_dir, args.n_train, "train", seed=1)
    test_records = make_split(images_dir, args.n_test, "test", seed=2)

    with open(args.out / "training.json", "w", encoding="utf-8") as f:
        json.dump(train_records, f, ensure_ascii=False, indent=2)
    with open(args.out / "testing.json", "w", encoding="utf-8") as f:
        json.dump(test_records, f, ensure_ascii=False, indent=2)

    print(f"สร้างข้อมูลปลอมเสร็จที่: {args.out}")
    print(f"train: {len(train_records)} ภาพ | test: {len(test_records)} ภาพ")


if __name__ == "__main__":
    main()
