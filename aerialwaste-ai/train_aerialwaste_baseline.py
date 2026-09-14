"""
train_aerialwaste_baseline.py
==============================

Baseline model: ตรวจจับว่าภาพถ่ายทางอากาศ/ดาวเทียม มีจุดทิ้งขยะผิดกฎหมายหรือไม่
(binary classification: is_candidate_location = 1 หรือ 0)

ใช้ transfer learning จาก ResNet18 (pretrained บน ImageNet) แล้ว fine-tune
ด้วยชุดข้อมูล AerialWaste — ไม่ต้อง train จากศูนย์ ใช้เวลาไม่นาน
แม้รันบน CPU (ถ้ามี GPU จะเร็วกว่ามาก)

------------------------------------------------------------------
ขั้นตอนเตรียมข้อมูลก่อนรันสคริปต์นี้ (ต้องทำเองบนเครื่องที่มีเน็ต
ที่เข้าถึง zenodo.org ได้ — สภาพแวดล้อมนี้เข้าถึงไม่ได้):
------------------------------------------------------------------
1. ไปที่ https://zenodo.org/record/7034381 ดาวน์โหลดไฟล์ภาพทั้งหมด
2. ไปที่ https://github.com/nahitorres/AerialWaste ดาวน์โหลด
   training.json และ testing.json
3. จัดโครงสร้างโฟลเดอร์แบบนี้:

   aerialwaste/
     ├── training.json
     ├── testing.json
     └── images/
         ├── xxx.jpg
         ├── yyy.jpg
         └── ...

4. ติดตั้งไลบรารีที่ต้องใช้:
   pip install -r requirements.txt --break-system-packages
   (ถ้ารันใน Colab ไม่ต้องติดตั้งอะไรเพิ่ม มีมาให้แล้ว)

5. รัน: python train_aerialwaste_baseline.py --data-dir /path/to/aerialwaste
------------------------------------------------------------------
"""

import argparse
import json
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from PIL import Image
from sklearn.metrics import classification_report, confusion_matrix

IMAGE_SIZE = 224  # ขนาดมาตรฐานของ ResNet


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./aerialwaste"),
                         help="โฟลเดอร์ที่มี training.json / testing.json / images/")
    parser.add_argument("--epochs", type=int, default=5,
                         help="จำนวนรอบ train (เริ่มน้อยๆ ก่อน ค่อยเพิ่มถ้าผลยังไม่ดี)")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--num-workers", type=int, default=0,
                         help="0 ปลอดภัยสุดสำหรับรันใน container/sandbox")
    parser.add_argument("--output", type=Path,
                         default=Path("aerialwaste_resnet18_baseline.pt"))
    return parser.parse_args()


# ============================================================
# Dataset — ตัวโหลดข้อมูลจาก JSON + โฟลเดอร์ภาพ
# ============================================================
class AerialWasteDataset(Dataset):
    """
    อ่าน training.json / testing.json ของ AerialWaste
    คืนค่าเป็น (ภาพ, label) โดย label = 1 คือมีจุดทิ้งขยะ, 0 คือไม่มี

    โครงสร้าง field ที่คาดไว้ต่อภาพ (อ้างอิงจาก README ของ
    https://github.com/nahitorres/AerialWaste):
      - file_name (str)
      - is_candidate_location (0/1)
    """

    def __init__(self, json_path, images_dir, transform=None):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # รองรับทั้งกรณี JSON เป็น list ของ record ตรงๆ
        # และกรณีเป็น dict ที่ครอบด้วย key เช่น {"images": [...]}
        if isinstance(data, dict):
            records = data.get("images")
            if records is None:
                # ไม่รู้ชื่อ key ที่แน่ชัด ลองเดาจาก value ที่เป็น list ของ dict
                for value in data.values():
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        records = value
                        break
            if records is None:
                raise ValueError(
                    f"ไม่รู้จักโครงสร้าง JSON ใน {json_path} (เป็น dict แต่หา list ของภาพไม่เจอ)\n"
                    f"keys ที่เจอ: {list(data.keys())}\n"
                    "เปิดไฟล์ดูโครงสร้างจริงแล้วแก้โค้ดส่วนนี้ให้ตรง"
                )
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError(f"ไม่รู้จักโครงสร้าง JSON ใน {json_path}: type={type(data)}")

        if records and "file_name" not in records[0]:
            raise KeyError(
                f"ไม่พบ key 'file_name' ใน record แรกของ {json_path}\n"
                f"keys ที่เจอจริง: {list(records[0].keys())}\n"
                "ให้แก้ AerialWasteDataset.__getitem__ ให้ใช้ key ที่ถูกต้อง"
            )

        self.records = records
        self.images_dir = Path(images_dir)
        self.transform = transform

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        rec = self.records[idx]
        img_path = self.images_dir / rec["file_name"]
        try:
            image = Image.open(img_path).convert("RGB")
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"หาไฟล์ภาพไม่เจอ: {img_path}\n"
                "ตรวจสอบว่าดาวน์โหลดภาพจาก Zenodo มาครบและวางไว้ใน images/ แล้ว"
            ) from e

        label = int(rec.get("is_candidate_location", 0))

        if self.transform:
            image = self.transform(image)

        return image, label


def build_model(device):
    model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
    num_features = model.fc.in_features
    model.fc = nn.Linear(num_features, 2)  # 2 classes: ไม่มีจุดทิ้งขยะ / มีจุดทิ้งขยะ
    return model.to(device)


def train_one_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0

    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * images.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return total_loss / total, correct / total


def evaluate(model, loader, device):
    model.eval()
    all_preds, all_labels = [], []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            outputs = model(images)
            preds = outputs.argmax(dim=1).cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(labels.numpy())

    print("\n=== ผลการประเมินบนชุดทดสอบ ===")
    print(classification_report(
        all_labels, all_preds,
        target_names=["ไม่มีจุดทิ้งขยะ", "มีจุดทิ้งขยะ"],
        zero_division=0,
    ))
    print("Confusion matrix (แถว=จริง, คอลัมน์=ทำนาย):")
    print(confusion_matrix(all_labels, all_preds))


def main():
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"ใช้งานบน: {device}")

    data_dir = args.data_dir
    images_dir = data_dir / "images"
    train_json = data_dir / "training.json"
    test_json = data_dir / "testing.json"

    if not train_json.exists() or not test_json.exists():
        raise FileNotFoundError(
            f"หา training.json / testing.json ไม่เจอใน {data_dir}\n"
            "โปรดดาวน์โหลดข้อมูลตามขั้นตอนใน docstring ด้านบนก่อน"
        )

    train_transform = transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                              std=[0.229, 0.224, 0.225]),
    ])
    eval_transform = transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                              std=[0.229, 0.224, 0.225]),
    ])

    print("กำลังโหลดข้อมูล...")
    train_dataset = AerialWasteDataset(train_json, images_dir, transform=train_transform)
    test_dataset = AerialWasteDataset(test_json, images_dir, transform=eval_transform)
    print(f"จำนวนภาพ train: {len(train_dataset)} | test: {len(test_dataset)}")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True,
                               num_workers=args.num_workers)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False,
                              num_workers=args.num_workers)

    print("กำลังสร้างโมเดล (ResNet18 pretrained)...")
    model = build_model(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    print("เริ่ม fine-tune...")
    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, optimizer, criterion, device)
        print(f"Epoch {epoch}/{args.epochs} — loss: {train_loss:.4f} | accuracy: {train_acc:.4f}")

    evaluate(model, test_loader, device)

    torch.save(model.state_dict(), args.output)
    print(f"\nบันทึกโมเดลแล้วที่: {args.output}")
    print("ขั้นถัดไป: เอาโมเดลนี้ไปทดสอบ (inference) กับภาพโดรน/ดาวเทียมของพื้นที่จริงในไทย")
    print("ดู infer_aerialwaste.py")


if __name__ == "__main__":
    main()
