"""
infer_detector.py
===================

ใช้โมเดลที่ train แล้ว (dumping_sites_fasterrcnn.pt) ทดสอบกับภาพใหม่
วาดกรอบสี่เหลี่ยม (bounding box) ที่โมเดลทายว่าเป็นจุดทิ้งขยะลงบนภาพ แล้วบันทึกไว้ดู

วิธีใช้:
    python infer_detector.py --model dumping_sites_fasterrcnn.pt --images-dir /path/to/images --output-dir ./predictions
"""

import argparse
from pathlib import Path

import torch
import torchvision
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.transforms import functional as F
from PIL import Image, ImageDraw, ImageFont

NUM_CLASSES = 2  # background + dumping-sites
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True,
                         help="path ไปยังไฟล์ .pt ที่ได้จาก train_detector.py")
    parser.add_argument("--images-dir", type=Path, required=True,
                         help="โฟลเดอร์ที่มีภาพที่จะทดสอบ")
    parser.add_argument("--output-dir", type=Path, default=Path("./predictions"),
                         help="โฟลเดอร์สำหรับบันทึกภาพที่วาดกรอบแล้ว")
    parser.add_argument("--score-threshold", type=float, default=0.5,
                         help="แสดงเฉพาะกล่องที่ความมั่นใจ >= ค่านี้")
    return parser.parse_args()


def load_model(model_path, device):
    model = torchvision.models.detection.fasterrcnn_resnet50_fpn_v2(weights=None)
    in_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_features, NUM_CLASSES)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.to(device)
    model.eval()
    return model


def draw_predictions(image, boxes, scores):
    image = image.copy()
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for box, score in zip(boxes, scores):
        x1, y1, x2, y2 = box.tolist()
        draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
        label = f"{score:.2f}"
        draw.text((x1, max(0, y1 - 12)), label, fill="red", font=font)

    return image


def main():
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"ใช้งานบน: {device}")

    if not args.model.exists():
        raise FileNotFoundError(f"ไม่พบไฟล์โมเดล: {args.model}")
    if not args.images_dir.is_dir():
        raise NotADirectoryError(f"ไม่พบโฟลเดอร์ภาพ: {args.images_dir}")

    image_paths = sorted(
        p for p in args.images_dir.iterdir() if p.suffix.lower() in VALID_EXTENSIONS
    )
    if not image_paths:
        raise FileNotFoundError(f"ไม่พบไฟล์ภาพ (.jpg/.jpeg/.png) ใน {args.images_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"กำลังโหลดโมเดลจาก {args.model}...")
    model = load_model(args.model, device)

    results = []
    with torch.no_grad():
        for path in image_paths:
            try:
                image = Image.open(path).convert("RGB")
            except Exception as e:
                print(f"ข้าม {path.name}: เปิดไฟล์ไม่ได้ ({e})")
                continue

            tensor = F.to_tensor(image).to(device)
            output = model([tensor])[0]

            keep = output["scores"] >= args.score_threshold
            boxes = output["boxes"][keep].cpu()
            scores = output["scores"][keep].cpu()

            annotated = draw_predictions(image, boxes, scores)
            out_path = args.output_dir / path.name
            annotated.save(out_path)

            results.append((path.name, len(boxes)))
            print(f"{path.name}: พบ {len(boxes)} จุด -> บันทึกที่ {out_path}")

    total_detections = sum(n for _, n in results)
    images_with_detection = sum(1 for _, n in results if n > 0)
    print(f"\n=== สรุป ===")
    print(f"ภาพทั้งหมด: {len(results)}")
    print(f"ภาพที่เจอจุดทิ้งขยะอย่างน้อย 1 จุด: {images_with_detection}/{len(results)}")
    print(f"จำนวนกล่องที่ทายรวมทั้งหมด: {total_detections}")
    print(f"ภาพที่วาดกรอบแล้วอยู่ที่: {args.output_dir}")


if __name__ == "__main__":
    main()
