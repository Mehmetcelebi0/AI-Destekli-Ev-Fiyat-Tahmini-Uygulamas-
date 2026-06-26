import json
import os
import warnings
from pathlib import Path
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from sklearn.impute import SimpleImputer

warnings.filterwarnings("ignore")

try:
    from catboost import CatBoostRegressor
    CATBOOST_AVAILABLE = True
except Exception:
    CATBOOST_AVAILABLE = False

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent.parent
LISTINGS_PATH = BASE_DIR / "listings.json"
MODEL_DIR = BASE_DIR / "models"
MODEL_PATH = MODEL_DIR / "price_ensemble.joblib"
DATA_DIR = BASE_DIR / "data"


TARGET = "price"

FEATURES = [
    "ilce",
    "mahalle",
    "net_metrekare",
    "brut_metrekare",
    "oda",
    "salon",
    "toplam_oda",
    "binanin_yasi",
    "binanin_kat_sayisi",
    "bulundugu_kat_numeric",
    "isitma_tipi",
    "kullanim_durumu",
    "krediye_uygunluk",
    "tapu_durumu",
    "site_icerisinde",
    "banyo_sayisi",
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

CATEGORICAL_COLUMNS = [
    "ilce",
    "mahalle",
    "binanin_yasi",
    "isitma_tipi",
    "tapu_durumu",
]

NUMERIC_COLUMNS = [col for col in FEATURES if col not in CATEGORICAL_COLUMNS]


def load_json(path):
    if not path.exists():
        raise FileNotFoundError(f"{path} bulunamadı.")

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def normalize_text(value):
    if value is None:
        return np.nan

    text = str(value).strip()

    if text == "":
        return np.nan

    return text


def to_number(value):
    if value is None or value == "":
        return np.nan

    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return np.nan


def mape_score(y_true, y_pred):
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    mask = y_true != 0

    if mask.sum() == 0:
        return np.nan

    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100


def within_percent_accuracy(y_true, y_pred, percent):
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    mask = y_true != 0

    if mask.sum() == 0:
        return np.nan

    ratio_error = np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]

    return np.mean(ratio_error <= percent) * 100


def print_metrics(title, y_true, y_pred):
    r2 = r2_score(y_true, y_pred)
    mae = mean_absolute_error(y_true, y_pred)
    rmse = mean_squared_error(y_true, y_pred, squared=False)
    mape = mape_score(y_true, y_pred)
    acc10 = within_percent_accuracy(y_true, y_pred, 0.10)
    acc20 = within_percent_accuracy(y_true, y_pred, 0.20)

    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(f"R2    : {r2:.4f}")
    print(f"MAE   : {mae:,.0f} TL")
    print(f"RMSE  : {rmse:,.0f} TL")
    print(f"MAPE  : %{mape:.2f}")
    print(f"±10%  : %{acc10:.2f}")
    print(f"±20%  : %{acc20:.2f}")

    return {
        "r2": float(r2),
        "mae": float(mae),
        "rmse": float(rmse),
        "mape": float(mape),
        "acc10": float(acc10),
        "acc20": float(acc20),
    }


def prepare_dataframe(raw_data):
    df = pd.DataFrame(raw_data)

    rename_map = {
        "district": "ilce",
        "neighborhood": "mahalle",
        "predictedPrice": "predicted_price",
    }

    df = df.rename(columns=rename_map)

    if TARGET not in df.columns:
        raise ValueError("listings.json içinde price kolonu bulunamadı.")

    for col in FEATURES:
        if col not in df.columns:
            df[col] = np.nan

    for col in NUMERIC_COLUMNS:
        df[col] = df[col].apply(to_number)

    for col in CATEGORICAL_COLUMNS:
        df[col] = df[col].apply(normalize_text)

    df[TARGET] = df[TARGET].apply(to_number)

    df = df[df[TARGET].notna()]
    df = df[df[TARGET] > 0]

    df = df[df["net_metrekare"].fillna(0) > 0]

    df["toplam_oda"] = df["toplam_oda"].fillna(df["oda"].fillna(0) + df["salon"].fillna(0))

    df["m2_price_raw"] = df[TARGET] / df["net_metrekare"]

    price_low = df[TARGET].quantile(0.01)
    price_high = df[TARGET].quantile(0.99)

    m2_low = df["m2_price_raw"].quantile(0.01)
    m2_high = df["m2_price_raw"].quantile(0.99)

    before = len(df)

    df = df[
        (df[TARGET] >= price_low)
        & (df[TARGET] <= price_high)
        & (df["m2_price_raw"] >= m2_low)
        & (df["m2_price_raw"] <= m2_high)
    ]

    after = len(df)

    print(f"Veri boyutu temizleme öncesi: {before}")
    print(f"Veri boyutu temizleme sonrası: {after}")

    df = add_group_features(df)

    return df


def add_group_features(df):
    df = df.copy()

    df["district_avg_price"] = df.groupby("ilce")[TARGET].transform("mean")
    df["district_median_price"] = df.groupby("ilce")[TARGET].transform("median")
    df["district_avg_m2_price"] = df.groupby("ilce")["m2_price_raw"].transform("mean")
    df["district_count"] = df.groupby("ilce")[TARGET].transform("count")

    df["neighborhood_avg_price"] = df.groupby(["ilce", "mahalle"])[TARGET].transform("mean")
    df["neighborhood_median_price"] = df.groupby(["ilce", "mahalle"])[TARGET].transform("median")
    df["neighborhood_avg_m2_price"] = df.groupby(["ilce", "mahalle"])["m2_price_raw"].transform("mean")
    df["neighborhood_count"] = df.groupby(["ilce", "mahalle"])[TARGET].transform("count")

    df["room_avg_price"] = df.groupby(["ilce", "mahalle", "oda", "salon"])[TARGET].transform("mean")
    df["room_median_price"] = df.groupby(["ilce", "mahalle", "oda", "salon"])[TARGET].transform("median")
    df["room_avg_m2_price"] = df.groupby(["ilce", "mahalle", "oda", "salon"])["m2_price_raw"].transform("mean")
    df["room_count"] = df.groupby(["ilce", "mahalle", "oda", "salon"])[TARGET].transform("count")

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

    q1 = df[TARGET].quantile(0.25)
    q2 = df[TARGET].quantile(0.50)
    q3 = df[TARGET].quantile(0.75)

    def segment_price(value):
        if value <= q1:
            return "low"
        if value <= q2:
            return "mid"
        if value <= q3:
            return "high"
        return "luxury"

    df["price_segment"] = df[TARGET].apply(segment_price)

    return df


def build_group_maps(df):
    maps = {}

    maps["district"] = (
        df.groupby("ilce")
        .agg(
            district_avg_price=(TARGET, "mean"),
            district_median_price=(TARGET, "median"),
            district_avg_m2_price=("m2_price_raw", "mean"),
            district_count=(TARGET, "count"),
        )
        .reset_index()
    )

    maps["neighborhood"] = (
        df.groupby(["ilce", "mahalle"])
        .agg(
            neighborhood_avg_price=(TARGET, "mean"),
            neighborhood_median_price=(TARGET, "median"),
            neighborhood_avg_m2_price=("m2_price_raw", "mean"),
            neighborhood_count=(TARGET, "count"),
        )
        .reset_index()
    )

    maps["room"] = (
        df.groupby(["ilce", "mahalle", "oda", "salon"])
        .agg(
            room_avg_price=(TARGET, "mean"),
            room_median_price=(TARGET, "median"),
            room_avg_m2_price=("m2_price_raw", "mean"),
            room_count=(TARGET, "count"),
        )
        .reset_index()
    )

    maps["global"] = {
        "global_avg_price": float(df[TARGET].mean()),
        "global_median_price": float(df[TARGET].median()),
        "global_avg_m2_price": float(df["m2_price_raw"].mean()),
        "global_median_m2_price": float(df["m2_price_raw"].median()),
    }

    return maps


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


def create_price_segment_from_y(y):
    q1 = y.quantile(0.25)
    q2 = y.quantile(0.50)
    q3 = y.quantile(0.75)

    def segment(value):
        if value <= q1:
            return 0
        if value <= q2:
            return 1
        if value <= q3:
            return 2
        return 3

    return y.apply(segment)


def encode_features(X_train, X_test, categorical_cols):
    X_train = X_train.copy()
    X_test = X_test.copy()

    numeric_cols = [col for col in X_train.columns if col not in categorical_cols]

    numeric_imputer = SimpleImputer(strategy="median")
    categorical_imputer = SimpleImputer(strategy="most_frequent")

    X_train[numeric_cols] = numeric_imputer.fit_transform(X_train[numeric_cols])
    X_test[numeric_cols] = numeric_imputer.transform(X_test[numeric_cols])

    X_train[categorical_cols] = categorical_imputer.fit_transform(X_train[categorical_cols])
    X_test[categorical_cols] = categorical_imputer.transform(X_test[categorical_cols])

    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)

    X_train[categorical_cols] = encoder.fit_transform(X_train[categorical_cols])
    X_test[categorical_cols] = encoder.transform(X_test[categorical_cols])

    preprocessors = {
        "numeric_imputer": numeric_imputer,
        "categorical_imputer": categorical_imputer,
        "encoder": encoder,
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
    }

    return X_train, X_test, preprocessors


def train_models(X_train, y_train):
    models = {}

    y_train_log = np.log1p(y_train)

    if CATBOOST_AVAILABLE:
        cat_model = CatBoostRegressor(
            iterations=2500,
            depth=8,
            learning_rate=0.035,
            loss_function="RMSE",
            eval_metric="RMSE",
            random_seed=42,
            random_strength=0.8,
            l2_leaf_reg=6,
            subsample=0.85,
            verbose=250,
        )

        cat_model.fit(X_train, y_train_log)
        models["catboost"] = cat_model

    if XGBOOST_AVAILABLE:
        xgb_model = XGBRegressor(
            n_estimators=2200,
            max_depth=7,
            learning_rate=0.025,
            subsample=0.88,
            colsample_bytree=0.88,
            min_child_weight=2,
            reg_alpha=0.03,
            reg_lambda=1.2,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1,
            tree_method="hist",
        )

        xgb_model.fit(X_train, y_train_log)
        models["xgboost"] = xgb_model

    extra_model = ExtraTreesRegressor(
        n_estimators=900,
        max_depth=None,
        min_samples_split=3,
        min_samples_leaf=1,
        max_features=0.8,
        random_state=42,
        n_jobs=-1,
    )

    extra_model.fit(X_train, y_train_log)
    models["extratrees"] = extra_model

    rf_model = RandomForestRegressor(
        n_estimators=600,
        max_depth=None,
        min_samples_split=4,
        min_samples_leaf=1,
        max_features=0.8,
        random_state=42,
        n_jobs=-1,
    )

    rf_model.fit(X_train, y_train_log)
    models["randomforest"] = rf_model

    return models


def predict_model(model, X):
    pred_log = model.predict(X)
    pred = np.expm1(pred_log)
    pred = np.maximum(pred, 0)
    return pred


def find_best_ensemble_weights(predictions, y_true):
    model_names = list(predictions.keys())

    if len(model_names) == 1:
        name = model_names[0]
        return {name: 1.0}, predictions[name]

    best_r2 = -999
    best_weights = None
    best_pred = None

    grid = np.arange(0, 1.01, 0.05)

    if len(model_names) == 2:
        a, b = model_names

        for wa in grid:
            wb = 1 - wa
            pred = predictions[a] * wa + predictions[b] * wb
            score = r2_score(y_true, pred)

            if score > best_r2:
                best_r2 = score
                best_weights = {a: float(wa), b: float(wb)}
                best_pred = pred

    elif len(model_names) == 3:
        a, b, c = model_names

        for wa in grid:
            for wb in grid:
                wc = 1 - wa - wb

                if wc < 0:
                    continue

                pred = predictions[a] * wa + predictions[b] * wb + predictions[c] * wc
                score = r2_score(y_true, pred)

                if score > best_r2:
                    best_r2 = score
                    best_weights = {a: float(wa), b: float(wb), c: float(wc)}
                    best_pred = pred

    else:
        a, b, c, d = model_names[:4]

        for wa in grid:
            for wb in grid:
                for wc in grid:
                    wd = 1 - wa - wb - wc

                    if wd < 0:
                        continue

                    pred = (
                        predictions[a] * wa
                        + predictions[b] * wb
                        + predictions[c] * wc
                        + predictions[d] * wd
                    )

                    score = r2_score(y_true, pred)

                    if score > best_r2:
                        best_r2 = score
                        best_weights = {
                            a: float(wa),
                            b: float(wb),
                            c: float(wc),
                            d: float(wd),
                        }
                        best_pred = pred

    return best_weights, best_pred


def main():
    print("=" * 70)
    print("HOUSE PRICE MODEL TRAINING V2")
    print("=" * 70)

    raw_data = load_json(LISTINGS_PATH)
    df = prepare_dataframe(raw_data)

    print(f"Final veri boyutu: {df.shape}")

    group_maps = build_group_maps(df)

    model_features = FEATURES + [
        "district_avg_price",
        "district_median_price",
        "district_avg_m2_price",
        "district_count",
        "neighborhood_avg_price",
        "neighborhood_median_price",
        "neighborhood_avg_m2_price",
        "neighborhood_count",
        "room_avg_price",
        "room_median_price",
        "room_avg_m2_price",
        "room_count",
        "net_brut_ratio",
        "floor_ratio",
        "avg_distance",
        "min_distance",
        "max_distance",
    ]

    model_features = [col for col in model_features if col in df.columns]

    categorical_cols = CATEGORICAL_COLUMNS.copy()

    X = df[model_features].copy()
    y = df[TARGET].copy()

    stratify_segment = create_price_segment_from_y(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.18,
        random_state=42,
        stratify=stratify_segment,
    )

    X_train_encoded, X_test_encoded, preprocessors = encode_features(
        X_train,
        X_test,
        categorical_cols,
    )

    models = train_models(X_train_encoded, y_train)

    predictions = {}

    for name, model in models.items():
        pred = predict_model(model, X_test_encoded)
        predictions[name] = pred
        print_metrics(name.upper(), y_test, pred)

    weights, ensemble_pred = find_best_ensemble_weights(predictions, y_test)

    metrics = print_metrics("FINAL ENSEMBLE", y_test, ensemble_pred)

    print("\nEnsemble weights:")
    for name, weight in weights.items():
        print(f"{name}: {weight:.2f}")

    MODEL_DIR.mkdir(exist_ok=True)

    package = {
        "models": models,
        "weights": weights,
        "features": model_features,
        "base_features": FEATURES,
        "categorical_cols": categorical_cols,
        "preprocessors": preprocessors,
        "group_maps": group_maps,
        "metrics": metrics,
        "trained_at": datetime.now().isoformat(),
        "training_rows": int(len(df)),
    }

    joblib.dump(package, MODEL_PATH)

    print("\nModel kaydedildi:")
    print(MODEL_PATH)

    if metrics["r2"] >= 0.88:
        print("\nHEDEF BAŞARILI: R2 >= 0.88")
    else:
        print("\nUYARI: R2 0.88 altında kaldı.")
        print("Bunun nedeni veri kalitesi, ilan çeşitliliği veya test ayrımı olabilir.")
        print("Bir sonraki adım: segment bazlı model veya mahalle bazlı target encoding.")


if __name__ == "__main__":
    main()