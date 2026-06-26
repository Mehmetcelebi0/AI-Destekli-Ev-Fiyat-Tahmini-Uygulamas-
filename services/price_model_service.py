import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "price_ensemble.joblib"
LISTINGS_PATH = BASE_DIR / "listings.json"


def format_price(price):
    try:
        return f"{int(round(float(price))):,}".replace(",", ".") + " TL"
    except Exception:
        return "0 TL"


def safe_number(value, default=0):
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def normalize_text(value):
    if value is None:
        return ""

    text = str(value).lower().strip()

    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
        "İ": "i",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return " ".join(text.split())


def normalize_neighborhood(value):
    text = normalize_text(value)
    return text.replace(" mahallesi", "").strip()


def load_json(path):
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_model_package():
    if not MODEL_PATH.exists():
        return None

    return joblib.load(MODEL_PATH)


def get_listing_price(item):
    return safe_number(item.get("price"))


def get_net_m2(item):
    return safe_number(item.get("net_metrekare"))


def get_room(item):
    return safe_number(item.get("oda"))


def get_salon(item):
    return safe_number(item.get("salon"))


def prepare_base_row(model_input, base_features):
    row = {}

    for feature in base_features:
        row[feature] = model_input.get(feature, None)

    return pd.DataFrame([row])


def apply_group_features_to_input(df, group_maps):
    df = df.copy()

    district_map = group_maps["district"]
    neighborhood_map = group_maps["neighborhood"]
    room_map = group_maps["room"]

    df = df.merge(district_map, on="ilce", how="left")
    df = df.merge(neighborhood_map, on=["ilce", "mahalle"], how="left")
    df = df.merge(room_map, on=["ilce", "mahalle", "oda", "salon"], how="left")

    global_stats = group_maps["global"]

    fill_cols = {
        "district_avg_price": global_stats["global_avg_price"],
        "district_median_price": global_stats["global_median_price"],
        "district_avg_m2_price": global_stats["global_avg_m2_price"],
        "district_count": 1,
        "neighborhood_avg_price": global_stats["global_avg_price"],
        "neighborhood_median_price": global_stats["global_median_price"],
        "neighborhood_avg_m2_price": global_stats["global_avg_m2_price"],
        "neighborhood_count": 1,
        "room_avg_price": global_stats["global_avg_price"],
        "room_median_price": global_stats["global_median_price"],
        "room_avg_m2_price": global_stats["global_avg_m2_price"],
        "room_count": 1,
    }

    for col, value in fill_cols.items():
        if col in df.columns:
            df[col] = df[col].fillna(value)

    df["net_brut_ratio"] = df["net_metrekare"] / df["brut_metrekare"].replace(0, np.nan)
    df["floor_ratio"] = df["bulundugu_kat_numeric"] / df["binanin_kat_sayisi"].replace(0, np.nan)

    distance_cols = [
        "ulasim_1_mesafe",
        "ulasim_2_mesafe",
        "ulasim_3_mesafe",
        "egitim_1_mesafe",
        "egitim_2_mesafe",
        "egitim_3_mesafe",
        "market_1_mesafe",
        "market_2_mesafe",
        "market_3_mesafe",
        "kafe_restoran_1_mesafe",
        "kafe_restoran_2_mesafe",
        "kafe_restoran_3_mesafe",
        "saglik_1_mesafe",
        "saglik_2_mesafe",
        "saglik_3_mesafe",
    ]

    existing_distance_cols = [col for col in distance_cols if col in df.columns]

    if existing_distance_cols:
        df["avg_distance"] = df[existing_distance_cols].mean(axis=1)
        df["min_distance"] = df[existing_distance_cols].min(axis=1)
        df["max_distance"] = df[existing_distance_cols].max(axis=1)

    return df


def encode_input(df, package):
    preprocessors = package["preprocessors"]

    numeric_imputer = preprocessors["numeric_imputer"]
    categorical_imputer = preprocessors["categorical_imputer"]
    encoder = preprocessors["encoder"]
    numeric_cols = preprocessors["numeric_cols"]
    categorical_cols = preprocessors["categorical_cols"]

    df = df.copy()

    for col in numeric_cols:
        if col not in df.columns:
            df[col] = np.nan

    for col in categorical_cols:
        if col not in df.columns:
            df[col] = np.nan

    df[numeric_cols] = numeric_imputer.transform(df[numeric_cols])
    df[categorical_cols] = categorical_imputer.transform(df[categorical_cols])
    df[categorical_cols] = encoder.transform(df[categorical_cols])

    final_features = package["features"]

    for col in final_features:
        if col not in df.columns:
            df[col] = 0

    return df[final_features]


def model_predict(package, model_input):
    base_features = package["base_features"]
    features = package["features"]
    group_maps = package["group_maps"]

    df = prepare_base_row(model_input, base_features)
    df = apply_group_features_to_input(df, group_maps)

    for col in features:
        if col not in df.columns:
            df[col] = np.nan

    X = encode_input(df[features], package)

    preds = {}

    for name, model in package["models"].items():
        pred_log = model.predict(X)
        pred = np.expm1(pred_log)
        preds[name] = float(pred[0])

    final_pred = 0

    for name, weight in package["weights"].items():
        final_pred += preds[name] * weight

    return max(final_pred, 0), preds


def find_similar_listings(model_input, limit=10):
    listings = load_json(LISTINGS_PATH)

    ilce = normalize_text(model_input.get("ilce"))
    mahalle = normalize_neighborhood(model_input.get("mahalle"))
    oda = safe_number(model_input.get("oda"), None)
    salon = safe_number(model_input.get("salon"), None)
    net_m2 = safe_number(model_input.get("net_metrekare"), None)

    def is_valid(item):
        return get_listing_price(item) > 0 and get_net_m2(item) > 0

    def same_district(item):
        return normalize_text(item.get("district")) == ilce

    def same_neighborhood(item):
        return normalize_neighborhood(item.get("neighborhood")) == mahalle

    def same_room(item):
        room_ok = oda is None or get_room(item) == oda
        salon_ok = salon is None or get_salon(item) == salon
        return room_ok and salon_ok

    def similar_m2(item):
        if not net_m2:
            return True

        item_m2 = get_net_m2(item)
        return net_m2 * 0.75 <= item_m2 <= net_m2 * 1.25

    strong = [
        item for item in listings
        if is_valid(item)
        and same_district(item)
        and same_neighborhood(item)
        and same_room(item)
        and similar_m2(item)
    ]

    if len(strong) >= 3:
        selected = strong
        match_level = "Aynı mahalle + aynı oda tipi + benzer m²"
        confidence = "Yüksek" if len(strong) >= 6 else "Orta-Yüksek"
    else:
        neighborhood_room = [
            item for item in listings
            if is_valid(item)
            and same_district(item)
            and same_neighborhood(item)
            and same_room(item)
        ]

        if len(neighborhood_room) >= 2:
            selected = neighborhood_room
            match_level = "Aynı mahalle + aynı oda tipi"
            confidence = "Orta-Yüksek"
        else:
            neighborhood_all = [
                item for item in listings
                if is_valid(item)
                and same_district(item)
                and same_neighborhood(item)
            ]

            if len(neighborhood_all) >= 2:
                selected = neighborhood_all
                match_level = "Aynı mahalle tüm ilanlar"
                confidence = "Orta"
            else:
                district_room = [
                    item for item in listings
                    if is_valid(item)
                    and same_district(item)
                    and same_room(item)
                ]

                selected = district_room
                match_level = "Aynı ilçe + aynı oda tipi"
                confidence = "Düşük-Orta" if len(district_room) >= 3 else "Düşük"

    selected = sorted(
        selected,
        key=lambda item: abs(get_net_m2(item) - net_m2)
        if net_m2
        else get_listing_price(item),
    )

    examples = []

    for item in selected[:limit]:
        price = get_listing_price(item)
        net = get_net_m2(item)
        m2_price = price / net if net else 0

        examples.append(
            {
                "title": item.get("title", "Benzer ilan"),
                "district": item.get("district"),
                "neighborhood": item.get("neighborhood"),
                "price": price,
                "price_text": format_price(price),
                "net_metrekare": net,
                "brut_metrekare": safe_number(item.get("brut_metrekare")),
                "oda": get_room(item),
                "salon": get_salon(item),
                "m2_price": round(m2_price),
                "m2_price_text": format_price(m2_price),
                "lat": safe_number(item.get("lat")),
                "lng": safe_number(item.get("lng")),
            }
        )

    return {
        "items": selected,
        "examples": examples,
        "match_level": match_level,
        "confidence": confidence,
    }


def build_market_summary(similar_result):
    items = similar_result["items"]

    prices = [get_listing_price(item) for item in items if get_listing_price(item) > 0]
    m2_prices = []

    for item in items:
        price = get_listing_price(item)
        net = get_net_m2(item)

        if price > 0 and net > 0:
            m2_prices.append(price / net)

    if not prices:
        return {
            "similar_listing_count": 0,
            "match_level": similar_result["match_level"],
            "confidence": "Düşük",
        }

    return {
        "similar_listing_count": len(items),
        "match_level": similar_result["match_level"],
        "confidence": similar_result["confidence"],
        "average_price": round(sum(prices) / len(prices)),
        "average_price_text": format_price(sum(prices) / len(prices)),
        "median_price": round(float(np.median(prices))),
        "median_price_text": format_price(float(np.median(prices))),
        "min_price": round(min(prices)),
        "min_price_text": format_price(min(prices)),
        "max_price": round(max(prices)),
        "max_price_text": format_price(max(prices)),
        "average_m2_price": round(sum(m2_prices) / len(m2_prices)) if m2_prices else 0,
        "average_m2_price_text": format_price(sum(m2_prices) / len(m2_prices))
        if m2_prices
        else "0 TL",
    }


def market_fallback_prediction(model_input, similar_result):
    net_m2 = safe_number(model_input.get("net_metrekare"))
    items = similar_result["items"]

    m2_prices = []

    for item in items:
        price = get_listing_price(item)
        net = get_net_m2(item)

        if price > 0 and net > 0:
            m2_prices.append(price / net)

    if not m2_prices or net_m2 <= 0:
        return None

    average_m2 = sum(m2_prices) / len(m2_prices)
    median_m2 = float(np.median(m2_prices))

    base_m2 = average_m2 * 0.45 + median_m2 * 0.55

    return base_m2 * net_m2


def apply_simple_adjustments(price, model_input):
    adjusted = float(price)
    notes = []

    site = safe_number(model_input.get("site_icerisinde"), None)
    kredi = safe_number(model_input.get("krediye_uygunluk"), None)
    banyo = safe_number(model_input.get("banyo_sayisi"), None)

    tapu = normalize_text(model_input.get("tapu_durumu"))
    isitma = normalize_text(model_input.get("isitma_tipi"))

    if site == 1:
        adjusted *= 1.03
        notes.append("Site içinde olduğu için yaklaşık %3 pozitif etki uygulandı.")

    if kredi == 2:
        adjusted *= 1.02
        notes.append("Krediye uygun olduğu için yaklaşık %2 pozitif etki uygulandı.")

    if "kat mulkiyeti" in tapu:
        adjusted *= 1.015
        notes.append("Kat mülkiyeti için küçük pozitif etki uygulandı.")

    if "merkezi" in isitma or "yerden" in isitma:
        adjusted *= 1.015
        notes.append("Isıtma tipi avantajlı kabul edildiği için küçük pozitif etki uygulandı.")

    if banyo is not None and banyo >= 2:
        adjusted *= 1.015
        notes.append("Banyo sayısı yüksek olduğu için küçük pozitif etki uygulandı.")

    return adjusted, notes


def predict_price(model_input):
    model_package = load_model_package()
    similar_result = find_similar_listings(model_input, limit=10)

    individual_model_predictions = {}

    if model_package is not None:
        estimated_price, individual_model_predictions = model_predict(
            model_package,
            model_input,
        )

        model_type = "trained_ensemble_model"
        model_metrics = model_package.get("metrics", {})
    else:
        estimated_price = market_fallback_prediction(model_input, similar_result)
        model_type = "fallback_market_m2_estimator"
        model_metrics = None

    if estimated_price is None or estimated_price <= 0:
        return {
            "success": False,
            "message": "Tahmin yapılamadı. Model dosyası veya benzer ilan verisi bulunamadı.",
            "input": model_input,
        }

    estimated_price, adjustment_notes = apply_simple_adjustments(
        estimated_price,
        model_input,
    )

    quick_sale_price = estimated_price * 0.96
    balanced_sale_price = estimated_price * 1.02
    high_sale_price = estimated_price * 1.08
    six_month_prediction = estimated_price * 1.035

    return {
        "success": True,
        "model_type": model_type,
        "message": "Fiyat tahmini başarıyla oluşturuldu.",
        "input": model_input,
        "prediction": {
            "estimated_price": round(estimated_price),
            "estimated_price_text": format_price(estimated_price),
            "quick_sale_price": round(quick_sale_price),
            "quick_sale_price_text": format_price(quick_sale_price),
            "balanced_sale_price": round(balanced_sale_price),
            "balanced_sale_price_text": format_price(balanced_sale_price),
            "high_sale_price": round(high_sale_price),
            "high_sale_price_text": format_price(high_sale_price),
            "six_month_prediction": round(six_month_prediction),
            "six_month_prediction_text": format_price(six_month_prediction),
        },
        "market_summary": build_market_summary(similar_result),
        "adjustment_notes": adjustment_notes,
        "example_listings": similar_result["examples"],
        "model_metrics": model_metrics,
        "individual_model_predictions": {
            name: round(value) for name, value in individual_model_predictions.items()
        },
    }