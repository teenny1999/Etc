"""
infer_aerialwaste.py
=====================

ใช้โมเดลที่ train แล้ว (aerialwaste_resnet18_baseline.pt) ทดสอบกับภาพโดรน/ดาวเทียม
ของพื้นที่จริงในไทย — ตามขั้นตอนที่ 5 ใน README ของโปรเจกต์

วิธีใช้:
    python infer_aerialwaste.py --model aerialwaste_resnet18_baseline.pt --images-dir ./my_thai_images

ผลลัพธ์: พิมพ์รายชื่อไฟล์ + คำทำนาย (มีจุดทิ้งขยะ / ไม่มี) + ความมั่นใจ (confidence)
เรียงจากความมั่นใจว่า "มีจุดทิ้งขยะ" มากไปน้อย เพื่อให้ไล่ตรวจภาพที่น่าสงสัยที่สุดก่อน
"""

import argparse
from pathlib import Path

import torch
import torch.nn.functional as F
from torchvision import models, transforms
from PIL import Image

IMAGE_SIZE = 224
CLASS_NAMES = ["ไม่มีจุดทิ้งขยะ", "มีจุดทิ้งขยะ"]
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png"}

eval_transform = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                          std=[0.229, 0.224, 0.225]),
])


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True,
                         help="path ไปยังไฟล์ .pt ที่ได้จาก train_aerialwaste_baseline.py")
    parser.add_argument("--images-dir", type=Path, required=True,
                         help="โฟลเดอร์ที่มีภาพโดรน/ดาวเทียมที่จะทดสอบ")
    return parser.parse_args()


def load_model(model_path, device):
    model = models.resnet18(weights=None)
    num_features = model.fc.in_features
    model.fc = torch.nn.Linear(num_features, 2)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.to(device)
    model.eval()
    return model


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

            tensor = eval_transform(image).unsqueeze(0).to(device)
            logits = model(tensor)
            probs = F.softmax(logits, dim=1).squeeze(0).cpu()
            pred_class = int(probs.argmax())
            results.append((path.name, pred_class, float(probs[1])))

    # เรียงจากความมั่นใจว่า "มีจุดทิ้งขยะ" มากไปน้อย
    results.sort(key=lambda r: r[2], reverse=True)

    print(f"\n=== ผลการทำนาย ({len(results)} ภาพ) ===")
    print(f"{'ไฟล์':<40} {'คำทำนาย':<18} {'ความมั่นใจว่ามีจุดทิ้งขยะ'}")
    for name, pred_class, waste_prob in results:
        print(f"{name:<40} {CLASS_NAMES[pred_class]:<18} {waste_prob:.1%}")


if __name__ == "__main__":
    main()
