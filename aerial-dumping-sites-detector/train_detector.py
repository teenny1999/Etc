"""
train_detector.py
===================

Object detection baseline: หา bounding box ของจุดทิ้งขยะผิดกฎหมายในภาพถ่ายทางอากาศ
ใช้ dataset "Aerial-Dumping-Sites" จาก Roboflow Universe:
https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites

ใช้ transfer learning จาก Faster R-CNN (ResNet50-FPN, pretrained บน COCO) แล้ว
fine-tune เฉพาะ box predictor ให้จับ class เดียวคือ "dumping-sites"

------------------------------------------------------------------
ขั้นตอนเตรียมข้อมูลก่อนรันสคริปต์นี้:
------------------------------------------------------------------
1. เข้า https://universe.roboflow.com/object-detection-of-illegal-dumping-sites/aerial-dumping-sites
   แท็บ "Dataset" -> เลือกเวอร์ชัน -> Download Dataset -> เลือกฟอร์แมต "COCO"
   -> เลือก "download zip to computer"
2. แตกไฟล์ zip จะได้โครงสร้าง:

   aerial-dumping-sites/
     ├── train/
     │   ├── _annotations.coco.json
     │   └── xxx.jpg, yyy.jpg, ...
     └── valid/
         ├── _annotations.coco.json
         └── ...

3. ติดตั้งไลบรารี: pip install -r requirements.txt --break-system-packages

4. รัน: python train_detector.py --data-dir /path/to/aerial-dumping-sites
------------------------------------------------------------------
"""

import argparse
import json
from pathlib import Path

import torch
import torchvision
from torch.utils.data import Dataset, DataLoader
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.transforms import functional as F
from PIL import Image

# id 0 ใน categories เป็น placeholder "none" ที่ Roboflow ใส่มาให้อัตโนมัติ ไม่ได้ใช้จริง
# annotation จริงทั้งหมดอ้าง category_id=1 ("dumping-sites") — เราแม็พเป็น label=1
# (label=0 สงวนไว้เป็น background ตามธรรมเนียมของ torchvision detection models)
NUM_CLASSES = 2  # background + dumping-sites


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./aerial-dumping-sites"))
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=2,
                         help="Faster R-CNN ใช้ memory เยอะ เริ่มจากค่าน้อยๆ ก่อน")
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None,
                         help="จำกัดจำนวนภาพต่อ split ไว้ smoke-test ให้เร็วขึ้น")
    parser.add_argument("--output", type=Path, default=Path("dumping_sites_fasterrcnn.pt"))
    return parser.parse_args()


class CocoDetectionDataset(Dataset):
    """อ่านโฟลเดอร์ style Roboflow COCO export (images/ + _annotations.coco.json รวมกัน)"""

    def __init__(self, split_dir, limit=None):
        split_dir = Path(split_dir)
        json_path = split_dir / "_annotations.coco.json"
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.split_dir = split_dir
        self.images_by_id = {img["id"]: img for img in data["images"]}

        self.anns_by_image = {}
        for ann in data["annotations"]:
            self.anns_by_image.setdefault(ann["image_id"], []).append(ann)

        self.image_ids = sorted(self.images_by_id.keys())
        if limit is not None:
            self.image_ids = self.image_ids[:limit]

    def __len__(self):
        return len(self.image_ids)

    def __getitem__(self, idx):
        image_id = self.image_ids[idx]
        info = self.images_by_id[image_id]
        image = Image.open(self.split_dir / info["file_name"]).convert("RGB")

        anns = self.anns_by_image.get(image_id, [])
        boxes, areas, iscrowd = [], [], []
        for ann in anns:
            x, y, w, h = ann["bbox"]
            boxes.append([x, y, x + w, y + h])
            areas.append(ann["area"])
            iscrowd.append(ann.get("iscrowd", 0))

        target = {
            "boxes": torch.as_tensor(boxes, dtype=torch.float32).reshape(-1, 4),
            "labels": torch.ones(len(anns), dtype=torch.int64),  # class เดียว: dumping-sites
            "image_id": torch.tensor([image_id]),
            "area": torch.as_tensor(areas, dtype=torch.float32),
            "iscrowd": torch.as_tensor(iscrowd, dtype=torch.int64),
        }

        image = F.to_tensor(image)  # ไม่ resize/normalize เอง — GeneralizedRCNNTransform ในตัวโมเดลจัดการให้
        return image, target


def collate_fn(batch):
    return tuple(zip(*batch))


def build_model(device):
    weights = torchvision.models.detection.FasterRCNN_ResNet50_FPN_V2_Weights.DEFAULT
    model = torchvision.models.detection.fasterrcnn_resnet50_fpn_v2(weights=weights)
    in_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_features, NUM_CLASSES)
    return model.to(device)


def train_one_epoch(model, loader, optimizer, device):
    model.train()
    total_loss = 0.0
    num_batches = 0

    for images, targets in loader:
        images = [img.to(device) for img in images]
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]

        loss_dict = model(images, targets)
        loss = sum(loss_dict.values())

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss += loss.item()
        num_batches += 1

    return total_loss / max(num_batches, 1)


@torch.no_grad()
def evaluate_simple(model, loader, device, score_threshold=0.5):
    """
    เช็คแบบง่ายๆ (ไม่ใช่ COCO mAP เต็มรูปแบบ): เทียบจำนวนกล่องที่ทำนาย
    (score >= threshold) กับจำนวนกล่องจริงต่อภาพ ไว้ดู sanity ของโมเดลเบื้องต้น
    ถ้าต้องการ mAP จริงให้ใช้ pycocotools + COCOeval กับผลลัพธ์ที่ได้จากฟังก์ชันนี้
    """
    model.eval()
    total_gt = 0
    total_pred = 0
    images_with_detection = 0
    total_images = 0

    for images, targets in loader:
        images = [img.to(device) for img in images]
        outputs = model(images)

        for target, output in zip(targets, outputs):
            total_images += 1
            total_gt += len(target["boxes"])
            keep = output["scores"] >= score_threshold
            n_pred = int(keep.sum())
            total_pred += n_pred
            if n_pred > 0:
                images_with_detection += 1

    print("\n=== ผลการประเมินแบบง่าย (ไม่ใช่ COCO mAP) ===")
    print(f"จำนวนภาพ: {total_images}")
    print(f"กล่องจริงทั้งหมด: {total_gt} | กล่องที่ทำนาย (score>={score_threshold}): {total_pred}")
    print(f"ภาพที่โมเดลเจอจุดทิ้งขยะอย่างน้อย 1 กล่อง: {images_with_detection}/{total_images}")


def main():
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"ใช้งานบน: {device}")

    train_dir = args.data_dir / "train"
    valid_dir = args.data_dir / "valid"
    if not (train_dir / "_annotations.coco.json").exists():
        raise FileNotFoundError(
            f"หา train/_annotations.coco.json ไม่เจอใน {args.data_dir}\n"
            "โปรดดาวน์โหลดข้อมูลตามขั้นตอนใน docstring ด้านบนก่อน"
        )

    print("กำลังโหลดข้อมูล...")
    train_dataset = CocoDetectionDataset(train_dir, limit=args.limit)
    valid_dataset = CocoDetectionDataset(valid_dir, limit=args.limit)
    print(f"จำนวนภาพ train: {len(train_dataset)} | valid: {len(valid_dataset)}")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True,
                               num_workers=args.num_workers, collate_fn=collate_fn)
    valid_loader = DataLoader(valid_dataset, batch_size=args.batch_size, shuffle=False,
                               num_workers=args.num_workers, collate_fn=collate_fn)

    print("กำลังสร้างโมเดล (Faster R-CNN ResNet50-FPN pretrained)...")
    model = build_model(device)

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(params, lr=args.lr)

    print("เริ่ม fine-tune...")
    for epoch in range(1, args.epochs + 1):
        train_loss = train_one_epoch(model, train_loader, optimizer, device)
        print(f"Epoch {epoch}/{args.epochs} — loss: {train_loss:.4f}")

    evaluate_simple(model, valid_loader, device)

    torch.save(model.state_dict(), args.output)
    print(f"\nบันทึกโมเดลแล้วที่: {args.output}")


if __name__ == "__main__":
    main()
