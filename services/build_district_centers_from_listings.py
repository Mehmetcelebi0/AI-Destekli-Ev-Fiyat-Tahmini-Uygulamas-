from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict


BASE_DIR = Path(__file__).resolve().parent

POSSIBLE_LISTINGS_PATHS = [
    BASE_DIR / "data" / "listings.json",
    BASE_DIR / "services" / "listings.json",
    BASE_DIR / "listings.json",
]

OUTPUT_PATHS = [
    BASE_DIR / "data" / "district_centers.json",
    BASE_DIR / "services" / "district_centers.json",
]


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def safe_float(value):
    try:
        if value is None or value == "":
            return None

        value = float(str(value).replace(",", "."))

        if value == 0:
            return None

        return value
    except Exception:
        return None


def find_listings_path() -> Path:
    for path in POSSIBLE_LISTINGS_PATHS:
        if path.exists():
            return path

    raise FileNotFoundError(
        "listings.json bulunamadı. Şu konumlardan biri olmalı:\n"
        "- data/listings.json\n"
        "- services/listings.json\n"
        "- listings.json"
    )


def build_centers(listings):
    grouped = defaultdict(lambda: {"lat": [], "lng": []})

    for item in listings:
        district = str(item.get("district") or "").strip()
        neighborhood = str(item.get("neighborhood") or "").strip()

        lat = safe_float(item.get("lat"))
        lng = safe_float(item.get("lng"))

        if not district or not neighborhood:
            continue

        if lat is None or lng is None:
            continue

        key = (district, neighborhood)
        grouped[key]["lat"].append(lat)
        grouped[key]["lng"].append(lng)

    centers = []

    for index, ((district, neighborhood), values) in enumerate(grouped.items(), start=1):
        lat_values = values["lat"]
        lng_values = values["lng"]

        if not lat_values or not lng_values:
            continue

        centers.append({
            "id": index,
            "district": district,
            "neighborhood": neighborhood,
            "lat": sum(lat_values) / len(lat_values),
            "lng": sum(lng_values) / len(lng_values),
            "listing_count": len(lat_values),
        })

    centers.sort(key=lambda x: (x["district"], x["neighborhood"]))

    return centers


def main():
    print("=" * 70)
    print("HOUSEAI DISTRICT CENTER BUILDER")
    print("=" * 70)

    listings_path = find_listings_path()
    print(f"Okunan listings dosyası: {listings_path}")

    listings = load_json(listings_path)

    if not isinstance(listings, list):
        raise ValueError("listings.json liste formatında değil.")

    centers = build_centers(listings)

    print(f"Toplam ilan sayısı: {len(listings)}")
    print(f"Oluşturulan mahalle merkezi sayısı: {len(centers)}")

    for output_path in OUTPUT_PATHS:
        save_json(output_path, centers)
        print(f"Kaydedildi: {output_path}")

    print("\nBitti. Şimdi Flask server'ı kapatıp tekrar aç.")
    print("CTRL + C")
    print("python app.py")


if __name__ == "__main__":
    main()