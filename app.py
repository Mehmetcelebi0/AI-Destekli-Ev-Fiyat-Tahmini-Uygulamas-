from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, session, redirect
from flask_cors import CORS

from services.price_model_service import predict_price
from services.houseai_ai_engine import map_chatbot_reply, seller_chatbot_reply

from services.admin_service import (
    verify_login,
    is_admin,
    build_admin_stats,
    get_users_summary,
    get_latest_added_listings,
    get_import_status,
    start_import_background,
)

from services.user_service import (
    register_user,
    verify_user_login,
    log_activity,
    get_user_activities,
    get_activity_summary,
    get_recent_activities,
)


# ---------------------------------------------------------
# FLASK APP AYARLARI
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PAGES_DIR = BASE_DIR / "pages"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

app = Flask(
    __name__,
    static_folder=str(STATIC_DIR),
    static_url_path="/static",
)

app.secret_key = "houseai-admin-secret-key-change-this"

CORS(app)

LISTINGS_PATH = DATA_DIR / "listings.json"
DISTRICT_CENTERS_PATH = DATA_DIR / "district_centers.json"


# ---------------------------------------------------------
# GENEL YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------

def load_json(path):
    path = Path(path)

    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return []


def normalize_text(text):
    text = str(text).lower().strip()

    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
        "İ": "i",
    }

    for tr_char, normal_char in replacements.items():
        text = text.replace(tr_char, normal_char)

    text = re.sub(r"\s+", " ", text)
    return text


def normalize_neighborhood_name(text):
    text = normalize_text(text)
    text = text.replace(" mahallesi", "").strip()
    return text


def contains_location_phrase(message, location_name):
    normalized_message = normalize_text(message)
    normalized_location = normalize_text(location_name)

    if not normalized_location:
        return False

    pattern = r"(?<![a-z0-9])" + re.escape(normalized_location) + r"(?![a-z0-9])"
    return re.search(pattern, normalized_message) is not None


def format_price(price):
    try:
        return f"{int(round(float(price))):,}".replace(",", ".") + " TL"
    except Exception:
        return "0 TL"


def safe_number(value, default=0):
    try:
        if value is None:
            return default

        return float(value)
    except Exception:
        return default


def get_listing_price(item):
    return safe_number(item.get("price"))


def get_predicted_price(item):
    return safe_number(item.get("predictedPrice", item.get("predicted_price", 0)))


# ---------------------------------------------------------
# İLÇE / MAHALLE / ODA BİLGİSİ BULMA
# ---------------------------------------------------------

def get_unique_districts_and_neighborhoods(listings):
    districts = set()
    neighborhoods = set()

    for item in listings:
        district = item.get("district", "")
        neighborhood = item.get("neighborhood", "")

        if district:
            districts.add(district)

        if neighborhood:
            neighborhoods.add(neighborhood)

    return sorted(districts), sorted(neighborhoods)


def get_neighborhoods_by_district(listings, district):
    result = set()
    district_norm = normalize_text(district)

    for item in listings:
        item_district = normalize_text(item.get("district", ""))

        if item_district == district_norm:
            neighborhood = item.get("neighborhood", "")

            if neighborhood:
                result.add(neighborhood)

    return sorted(result)


def extract_room_info(message):
    normalized = normalize_text(message)
    match = re.search(r"(\d+)\s*\+\s*(\d+)", normalized)

    if not match:
        return None, None

    oda = int(match.group(1))
    salon = int(match.group(2))

    return oda, salon


def extract_location(message, listings):
    districts, neighborhoods = get_unique_districts_and_neighborhoods(listings)

    found_district = None
    found_neighborhood = None

    for district in sorted(districts, key=len, reverse=True):
        if contains_location_phrase(message, district):
            found_district = district
            break

    if found_district:
        candidate_neighborhoods = get_neighborhoods_by_district(listings, found_district)
    else:
        candidate_neighborhoods = neighborhoods

    for neighborhood in sorted(candidate_neighborhoods, key=len, reverse=True):
        full_name = neighborhood
        short_name = normalize_neighborhood_name(neighborhood)

        if contains_location_phrase(message, full_name) or contains_location_phrase(message, short_name):
            found_neighborhood = neighborhood
            break

    return found_district, found_neighborhood


def find_district_from_plain_text(message, listings):
    districts, _ = get_unique_districts_and_neighborhoods(listings)

    for district in sorted(districts, key=len, reverse=True):
        if contains_location_phrase(message, district):
            return district

    return None


def find_neighborhood_from_plain_text(message, listings, district=None):
    if district:
        neighborhoods = get_neighborhoods_by_district(listings, district)
    else:
        _, neighborhoods = get_unique_districts_and_neighborhoods(listings)

    for neighborhood in sorted(neighborhoods, key=len, reverse=True):
        full_name = neighborhood
        short_name = normalize_neighborhood_name(neighborhood)

        if contains_location_phrase(message, full_name) or contains_location_phrase(message, short_name):
            return neighborhood

    return None


def find_district_for_neighborhood(neighborhood, listings):
    if not neighborhood:
        return None

    neighborhood_norm = normalize_neighborhood_name(neighborhood)

    for item in listings:
        item_neighborhood = normalize_neighborhood_name(item.get("neighborhood", ""))

        if item_neighborhood == neighborhood_norm:
            return item.get("district")

    return None


def get_location_from_message_or_context(message, listings, state, context):
    district, neighborhood = extract_location(message, listings)

    if not district:
        district = (
            state.get("lastDistrict")
            or state.get("district")
            or context.get("district")
        )

    if not neighborhood:
        neighborhood = (
            state.get("lastNeighborhood")
            or state.get("neighborhood")
            or context.get("neighborhood")
        )

    if neighborhood and not district:
        district = find_district_for_neighborhood(neighborhood, listings)

    return district, neighborhood


def get_area_center(district, neighborhood=None):
    centers = load_json(DISTRICT_CENTERS_PATH)
    listings = load_json(LISTINGS_PATH)

    district_norm = normalize_text(district)
    neighborhood_norm = normalize_neighborhood_name(neighborhood or "")

    # 1) Önce district_centers.json içinde tam mahalle merkezi ara
    if neighborhood:
        for item in centers:
            item_district = normalize_text(item.get("district", ""))
            item_neighborhood = normalize_neighborhood_name(item.get("neighborhood", ""))

            if item_district == district_norm and item_neighborhood == neighborhood_norm:
                lat = safe_number(item.get("lat"), None)
                lng = safe_number(item.get("lng"), None)

                if lat is not None and lng is not None:
                    return {
                        "lat": lat,
                        "lng": lng,
                        "district": item.get("district") or district,
                        "neighborhood": item.get("neighborhood") or neighborhood,
                        "source": "district_centers_neighborhood",
                    }

    # 2) Mahalle merkezi yoksa listings.json içindeki aynı mahalle ilanlarından ortalama koordinat üret
    if neighborhood:
        lat_values = []
        lng_values = []

        for item in listings:
            item_district = normalize_text(item.get("district", ""))
            item_neighborhood = normalize_neighborhood_name(item.get("neighborhood", ""))

            if item_district != district_norm:
                continue

            if item_neighborhood != neighborhood_norm:
                continue

            lat = safe_number(item.get("lat"), None)
            lng = safe_number(item.get("lng"), None)

            if lat is not None and lng is not None and lat != 0 and lng != 0:
                lat_values.append(lat)
                lng_values.append(lng)

        if lat_values and lng_values:
            return {
                "lat": sum(lat_values) / len(lat_values),
                "lng": sum(lng_values) / len(lng_values),
                "district": district,
                "neighborhood": neighborhood,
                "source": "listings_neighborhood_average",
            }

    # 3) Mahallede koordinat yoksa district_centers.json içinde ilçe merkezi ara
    for item in centers:
        item_district = normalize_text(item.get("district", ""))

        if item_district == district_norm:
            lat = safe_number(item.get("lat"), None)
            lng = safe_number(item.get("lng"), None)

            if lat is not None and lng is not None:
                return {
                    "lat": lat,
                    "lng": lng,
                    "district": item.get("district") or district,
                    "neighborhood": item.get("neighborhood") or neighborhood,
                    "source": "district_centers_district",
                }

    # 4) İlçe merkezi de yoksa listings.json içindeki ilçe ilanlarından ortalama koordinat üret
    lat_values = []
    lng_values = []

    for item in listings:
        item_district = normalize_text(item.get("district", ""))

        if item_district != district_norm:
            continue

        lat = safe_number(item.get("lat"), None)
        lng = safe_number(item.get("lng"), None)

        if lat is not None and lng is not None and lat != 0 and lng != 0:
            lat_values.append(lat)
            lng_values.append(lng)

    if lat_values and lng_values:
        return {
            "lat": sum(lat_values) / len(lat_values),
            "lng": sum(lng_values) / len(lng_values),
            "district": district,
            "neighborhood": neighborhood,
            "source": "listings_district_average",
        }

    return None

# ---------------------------------------------------------
# İLAN FİLTRELEME VE PİYASA ANALİZİ
# ---------------------------------------------------------

def filter_listings(listings, district=None, neighborhood=None, oda=None, salon=None):
    filtered = []

    for item in listings:
        item_district = normalize_text(item.get("district", ""))
        item_neighborhood = normalize_neighborhood_name(item.get("neighborhood", ""))

        if district and item_district != normalize_text(district):
            continue

        if neighborhood and item_neighborhood != normalize_neighborhood_name(neighborhood):
            continue

        if oda is not None:
            if int(safe_number(item.get("oda"))) != int(oda):
                continue

        if salon is not None:
            if int(safe_number(item.get("salon"))) != int(salon):
                continue

        price = get_listing_price(item)
        net_m2 = safe_number(item.get("net_metrekare"))

        if price <= 0 or net_m2 <= 0:
            continue

        filtered.append(item)

    return filtered


def calculate_market_summary(filtered):
    prices = [
        get_listing_price(item)
        for item in filtered
        if get_listing_price(item) > 0
    ]

    m2_prices = []

    for item in filtered:
        price = get_listing_price(item)
        net_m2 = safe_number(item.get("net_metrekare"))

        if price > 0 and net_m2 > 0:
            m2_prices.append(price / net_m2)

    if not prices:
        return None

    average_price = sum(prices) / len(prices)
    median_price = statistics.median(prices)
    min_price = min(prices)
    max_price = max(prices)
    average_m2_price = sum(m2_prices) / len(m2_prices) if m2_prices else 0

    return {
        "count": len(filtered),
        "average_price": average_price,
        "median_price": median_price,
        "min_price": min_price,
        "max_price": max_price,
        "average_m2_price": average_m2_price,
    }


def prepare_example_listings(filtered, limit=None):
    summary = calculate_market_summary(filtered)

    if not summary:
        return []

    avg_price = summary["average_price"]

    sorted_items = sorted(
        filtered,
        key=lambda item: abs(get_listing_price(item) - avg_price)
    )

    if limit is not None:
        sorted_items = sorted_items[:limit]

    examples = []

    for item in sorted_items:
        examples.append({
            "id": item.get("id"),
            "title": item.get("title", "İlan"),
            "district": item.get("district"),
            "neighborhood": item.get("neighborhood"),
            "price": get_listing_price(item),
            "price_text": format_price(get_listing_price(item)),
            "predicted_price": get_predicted_price(item),
            "predicted_price_text": format_price(get_predicted_price(item)),
            "lat": safe_number(item.get("lat")),
            "lng": safe_number(item.get("lng")),
            "net_metrekare": safe_number(item.get("net_metrekare")),
            "brut_metrekare": safe_number(item.get("brut_metrekare")),
            "oda": int(safe_number(item.get("oda"))),
            "salon": int(safe_number(item.get("salon"))),
            "binanin_yasi": item.get("binanin_yasi"),
            "banyo_sayisi": int(safe_number(item.get("banyo_sayisi"))),
            "status": item.get("status", "normal"),
        })

    return examples


# ---------------------------------------------------------
# NİYET ALGILAMA
# ---------------------------------------------------------

def is_add_listing_intent(message):
    normalized = normalize_text(message)

    keywords = [
        "ilanimi girmek",
        "ilan girmek",
        "ev ilanimi girmek",
        "evimi eklemek",
        "ilan eklemek",
        "ev eklemek",
        "konum secmek",
        "evimin konumu",
        "ev ilan",
        "ev ilani",
        "ev ilanı",
        "ev ilani girmek",
        "ev ilanı girmek",
        "ev ilani girecegim",
        "ev ilanı gireceğim",
        "ev ilani girecem",
        "ev ilanı girecem",
        "ev ilan girecem",
        "ilan girecem",
        "ilan girecegim",
        "ilan gireceğim",
        "evimi satacagim",
        "evimi satacağım",
        "evimi satmak istiyorum",
        "satmak istiyorum",
    ]

    return any(normalize_text(keyword) in normalized for keyword in keywords)


def is_price_question(message):
    normalized = normalize_text(message)

    keywords = [
        "ortalama",
        "ne kadar",
        "kac tl",
        "kaç tl",
        "fiyat",
        "piyasa",
        "deger",
        "değer",
        "eder",
        "gidiyor",
        "kaç",
        "tl",
        "kaça",
        "kaca",
    ]

    return any(normalize_text(keyword) in normalized for keyword in keywords)


# ---------------------------------------------------------
# ADMIN / USER AUTH YARDIMCILARI
# ---------------------------------------------------------

def get_current_admin_user():
    user = session.get("admin_user")

    if not user:
        return None

    if not is_admin(user):
        return None

    return user


def admin_api_required():
    user = get_current_admin_user()

    if not user:
        return None, (jsonify({
            "success": False,
            "message": "Admin girişi gerekli."
        }), 401)

    return user, None


def get_current_user():
    return session.get("user")


def user_api_required():
    user = get_current_user()

    if not user:
        return None, (jsonify({
            "success": False,
            "message": "Kullanıcı girişi gerekli."
        }), 401)

    return user, None


# ---------------------------------------------------------
# SAYFA ROUTE'LARI
# ---------------------------------------------------------

@app.route("/")
@app.route("/index.html")
@app.route("/map")
def home():
    return send_from_directory(PAGES_DIR, "index.html")


@app.route("/predict.html")
@app.route("/predict")
def predict_page():
    return send_from_directory(PAGES_DIR, "predict.html")


@app.route("/seller.html")
@app.route("/seller")
def seller_page():
    return send_from_directory(PAGES_DIR, "seller.html")


@app.route("/admin-login")
def admin_login_page():
    return send_from_directory(PAGES_DIR, "admin_login.html")


@app.route("/admin")
def admin_page():
    user = get_current_admin_user()

    if not user:
        return redirect("/admin-login")

    return send_from_directory(PAGES_DIR, "admin.html")


@app.route("/login")
def user_login_page():
    return send_from_directory(PAGES_DIR, "user_login.html")


@app.route("/register")
def user_register_page():
    return send_from_directory(PAGES_DIR, "user_register.html")


@app.route("/user-dashboard")
def user_dashboard_page():
    user = get_current_user()

    if not user:
        return redirect("/login")

    return send_from_directory(PAGES_DIR, "user_dashboard.html")


# ---------------------------------------------------------
# JSON DATA ROUTE'LARI
# map.js eski şekilde /listings.json ve /district_centers.json çağırdığı için
# bu route'lar şart.
# ---------------------------------------------------------

@app.route("/listings.json")
def serve_listings_json():
    return send_from_directory(DATA_DIR, "listings.json")


@app.route("/district_centers.json")
def serve_district_centers_json():
    return send_from_directory(DATA_DIR, "district_centers.json")


# ---------------------------------------------------------
# ADMIN API ROUTE'LARI
# ---------------------------------------------------------

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json() or {}

    email = data.get("email", "")
    password = data.get("password", "")

    user = verify_login(email, password)

    if not user or not is_admin(user):
        return jsonify({
            "success": False,
            "message": "E-posta veya şifre hatalı."
        }), 401

    session["admin_user"] = user

    return jsonify({
        "success": True,
        "message": "Giriş başarılı.",
        "user": user,
    })


@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop("admin_user", None)

    return jsonify({
        "success": True,
        "message": "Çıkış yapıldı."
    })


@app.route("/api/admin/me", methods=["GET"])
def api_admin_me():
    user, error = admin_api_required()

    if error:
        return error

    return jsonify({
        "success": True,
        "user": user,
    })


@app.route("/api/admin/stats", methods=["GET"])
def api_admin_stats():
    user, error = admin_api_required()

    if error:
        return error

    stats = build_admin_stats()
    stats["activity_summary"] = get_activity_summary()

    return jsonify({
        "success": True,
        "stats": stats,
    })


@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    user, error = admin_api_required()

    if error:
        return error

    summary = get_users_summary()

    return jsonify({
        "success": True,
        "users": summary["latest_users"],
        "summary": summary,
    })


@app.route("/api/admin/latest-imported-listings", methods=["GET"])
def api_admin_latest_imported_listings():
    user, error = admin_api_required()

    if error:
        return error

    items = get_latest_added_listings(limit=50)

    return jsonify({
        "success": True,
        "items": items,
    })


@app.route("/api/admin/run-import", methods=["POST"])
def api_admin_run_import():
    user, error = admin_api_required()

    if error:
        return error

    result = start_import_background()
    status_code = 200 if result.get("success") else 409

    return jsonify(result), status_code


@app.route("/api/admin/import-status", methods=["GET"])
def api_admin_import_status():
    user, error = admin_api_required()

    if error:
        return error

    status = get_import_status()

    return jsonify({
        "success": True,
        "status": status,
    })


@app.route("/api/admin/activities", methods=["GET"])
def api_admin_activities():
    user, error = admin_api_required()

    if error:
        return error

    activities = get_recent_activities(limit=100)

    return jsonify({
        "success": True,
        "activities": activities,
    })


# ---------------------------------------------------------
# USER API ROUTE'LARI
# ---------------------------------------------------------

@app.route("/api/user/register", methods=["POST"])
def api_user_register():
    data = request.get_json() or {}

    result = register_user(
        name=data.get("name", ""),
        email=data.get("email", ""),
        password=data.get("password", ""),
    )

    if not result.get("success"):
        return jsonify(result), 400

    session["user"] = result["user"]

    return jsonify(result)


@app.route("/api/user/login", methods=["POST"])
def api_user_login():
    data = request.get_json() or {}

    user = verify_user_login(
        email=data.get("email", ""),
        password=data.get("password", ""),
    )

    if not user:
        return jsonify({
            "success": False,
            "message": "E-posta veya şifre hatalı."
        }), 401

    session["user"] = user

    return jsonify({
        "success": True,
        "message": "Giriş başarılı.",
        "user": user,
    })


@app.route("/api/user/logout", methods=["POST"])
def api_user_logout():
    user = session.get("user")

    if user:
        log_activity(
            user=user,
            action_type="logout",
            description="Kullanıcı çıkış yaptı.",
            meta={},
        )

    session.pop("user", None)

    return jsonify({
        "success": True,
        "message": "Çıkış yapıldı."
    })


@app.route("/api/user/me", methods=["GET"])
def api_user_me():
    user, error = user_api_required()

    if error:
        return error

    return jsonify({
        "success": True,
        "user": user,
    })


@app.route("/api/user/activities", methods=["GET"])
def api_user_activities():
    user, error = user_api_required()

    if error:
        return error

    activities = get_user_activities(user_id=user["id"], limit=100)

    return jsonify({
        "success": True,
        "activities": activities,
    })


# ---------------------------------------------------------
# ANA API ROUTE'LARI
# ---------------------------------------------------------

@app.route("/api/map-chatbot", methods=["POST"])
def map_chatbot():
    data = request.get_json() or {}
    result = map_chatbot_reply(data)

    user = session.get("user")

    if user:
        log_activity(
            user=user,
            action_type="map_chat",
            description="Kullanıcı harita chatbot ile konuştu.",
            meta={
                "message": str(data.get("message", ""))[:300],
            },
        )

    return jsonify(result)


@app.route("/api/seller-chatbot", methods=["POST"])
def seller_chatbot():
    data = request.get_json() or {}
    result = seller_chatbot_reply(data)

    user = session.get("user")

    if user:
        message = str(data.get("message", ""))

        log_activity(
            user=user,
            action_type="seller_analysis",
            description="Kullanıcı satış danışmanı ile analiz yaptı.",
            meta={
                "message": message[:300],
                "intent": result.get("intent") if isinstance(result, dict) else None,
            },
        )

    return jsonify(result)


@app.route("/api/basic-price-predict", methods=["POST"])
def basic_price_predict():
    data = request.get_json() or {}
    result = predict_price(data)

    user = session.get("user")

    if user:
        predicted_price = None

        if isinstance(result, dict):
            predicted_price = (
                result.get("predicted_price")
                or result.get("prediction")
                or result.get("price")
                or result.get("estimated_price")
                or result.get("predictedPrice")
            )

        log_activity(
            user=user,
            action_type="price_prediction",
            description="Kullanıcı ev fiyat tahmini yaptı.",
            meta={
                "district": data.get("ilce"),
                "neighborhood": data.get("mahalle"),
                "oda": data.get("oda"),
                "salon": data.get("salon"),
                "net_metrekare": data.get("net_metrekare"),
                "predicted_price": predicted_price,
            },
        )

    return jsonify(result)


@app.route("/api/chatbot", methods=["POST"])
def chatbot():
    data = request.get_json() or {}

    message = data.get("message", "")
    state = data.get("state", {}) or {}
    context = data.get("context", {}) or {}

    user = session.get("user")

    if user:
        log_activity(
            user=user,
            action_type="map_chat",
            description="Kullanıcı harita chatbot ile konuştu.",
            meta={
                "message": str(message)[:300],
            },
        )

    listings = load_json(LISTINGS_PATH)

    if not listings:
        return jsonify({
            "reply": "İlan verisi bulunamadı. data/listings.json dosyasını kontrol etmelisin.",
            "action": None,
            "data": None,
            "state": state,
        })

    # -----------------------------------------------------
    # 1) EV İLANI GİRME / KONUM SEÇME AKIŞI
    # -----------------------------------------------------

    if is_add_listing_intent(message):
        new_state = {
            "mode": "add_listing",
            "step": "ask_district",
        }

        return jsonify({
            "reply": "Tabii, ev ilanını girmek için yardımcı olayım. Önce ilçeyi yazar mısın? Örnek: Kağıthane",
            "action": None,
            "data": None,
            "state": new_state,
        })

    if state.get("mode") == "add_listing" and state.get("step") == "ask_district":
        district = find_district_from_plain_text(message, listings)

        if not district:
            return jsonify({
                "reply": "İlçeyi tam anlayamadım. Mesela 'Kağıthane', 'Kadıköy', 'Beşiktaş' gibi yazabilir misin?",
                "action": None,
                "data": None,
                "state": state,
            })

        new_state = {
            "mode": "add_listing",
            "step": "ask_neighborhood",
            "district": district,
            "lastDistrict": district,
        }

        return jsonify({
            "reply": f"Tamam, ilçe: {district}. Şimdi mahallenin adını yazar mısın? Örnek: Hamidiye Mahallesi",
            "action": None,
            "data": None,
            "state": new_state,
        })

    if state.get("mode") == "add_listing" and state.get("step") == "ask_neighborhood":
        district = state.get("district") or state.get("lastDistrict")

        neighborhood = find_neighborhood_from_plain_text(
            message=message,
            listings=listings,
            district=district,
        )

        if not neighborhood:
            return jsonify({
                "reply": "Mahalle adını tam anlayamadım. Örneğin 'Hamidiye Mahallesi' veya 'Merkez' şeklinde yazabilir misin?",
                "action": None,
                "data": None,
                "state": state,
            })

        center = get_area_center(district, neighborhood)

        if not center:
            return jsonify({
                "reply": f"{district} / {neighborhood} için harita merkezi bulamadım. data/district_centers.json dosyasını kontrol etmek lazım.",
                "action": None,
                "data": None,
                "state": {
                    "mode": "area_context",
                    "lastDistrict": district,
                    "lastNeighborhood": neighborhood,
                },
            })

        return jsonify({
            "reply": f"Süper. Haritayı {district} / {neighborhood} bölgesine götürüyorum. Haritada evinin tam konumuna tıkla.",
            "action": "fly_to_area_and_select",
            "data": {
                "district": district,
                "neighborhood": neighborhood,
                "lat": center["lat"],
                "lng": center["lng"],
                "zoom": 16,
            },
            "state": {
                "mode": "area_context",
                "lastDistrict": district,
                "lastNeighborhood": neighborhood,
            },
        })

    # -----------------------------------------------------
    # 2) FİYAT / PİYASA ANALİZİ AKIŞI
    # -----------------------------------------------------

    if is_price_question(message):
        district, neighborhood = get_location_from_message_or_context(
            message=message,
            listings=listings,
            state=state,
            context=context,
        )

        oda, salon = extract_room_info(message)

        if not district:
            return jsonify({
                "reply": "Hangi ilçe için fiyat analizi istediğini anlayamadım. Örnek: 'Kağıthane Hamidiye Mahallesi 3+1 ortalama ne kadar?'",
                "action": None,
                "data": None,
                "state": state,
            })

        filtered = filter_listings(
            listings=listings,
            district=district,
            neighborhood=neighborhood,
            oda=oda,
            salon=salon,
        )

        fallback_used = False

        if len(filtered) == 0 and neighborhood:
            room_info = ""

            if oda is not None and salon is not None:
                room_info = f" {oda}+{salon}"

            return jsonify({
                "reply": (
                    f"{district} / {neighborhood}{room_info} için uygun ilan bulunamadı.\n\n"
                    f"Bu yüzden tüm {district} ilçesine genişletmedim. "
                    f"Şu an sadece seçtiğin mahalle üzerinden arama yapıyorum."
                ),
                "action": "show_market_result",
                "data": {
                    "district": district,
                    "neighborhood": neighborhood,
                    "oda": oda,
                    "salon": salon,
                    "summary": None,
                    "examples": [],
                    "center": None,
                },
                "state": {
                    **state,
                    "mode": "area_context",
                    "lastDistrict": district,
                    "lastNeighborhood": neighborhood,
                },
            })

        if len(filtered) == 0 and not neighborhood and oda is not None:
            filtered = filter_listings(
                listings=listings,
                district=district,
                neighborhood=None,
                oda=None,
                salon=None,
            )

            fallback_used = True

        summary = calculate_market_summary(filtered)

        if not summary:
            return jsonify({
                "reply": "Bu kriterlere uygun ilan bulamadım. Daha genel arayabilirsin. Örnek: 'Kağıthane ortalama fiyat ne kadar?'",
                "action": None,
                "data": None,
                "state": {
                    **state,
                    "lastDistrict": district,
                    "lastNeighborhood": neighborhood,
                },
            })

        examples = prepare_example_listings(filtered, limit=None)

        room_text = ""

        if oda is not None and salon is not None and not fallback_used:
            room_text = f" {oda}+{salon}"

        area_text = district

        if neighborhood:
            area_text += f" / {neighborhood}"

        fallback_note = ""

        if fallback_used:
            fallback_note = "\n\nNot: Tam kriterde yeterli ilan bulunamadığı için daha geniş veriyle hesapladım."

        reply = (
            f"{area_text}{room_text} ilanları için yaklaşık piyasa özeti:\n\n"
            f"Ortalama fiyat: {format_price(summary['average_price'])}\n"
            f"Medyan fiyat: {format_price(summary['median_price'])}\n"
            f"Ortalama m² fiyatı: {format_price(summary['average_m2_price'])}\n"
            f"İlan sayısı: {summary['count']}\n"
            f"Fiyat aralığı: {format_price(summary['min_price'])} - {format_price(summary['max_price'])}"
            f"{fallback_note}"
        )

        center = None

        if examples:
            center = {
                "lat": examples[0]["lat"],
                "lng": examples[0]["lng"],
                "zoom": 15,
            }
        else:
            area_center = get_area_center(district, neighborhood)

            if area_center:
                center = {
                    "lat": area_center["lat"],
                    "lng": area_center["lng"],
                    "zoom": 15,
                }

        return jsonify({
            "reply": reply,
            "action": "show_market_result",
            "data": {
                "district": district,
                "neighborhood": neighborhood,
                "oda": oda,
                "salon": salon,
                "summary": {
                    "count": summary["count"],
                    "average_price": summary["average_price"],
                    "average_price_text": format_price(summary["average_price"]),
                    "median_price": summary["median_price"],
                    "median_price_text": format_price(summary["median_price"]),
                    "average_m2_price": summary["average_m2_price"],
                    "average_m2_price_text": format_price(summary["average_m2_price"]),
                    "min_price": summary["min_price"],
                    "min_price_text": format_price(summary["min_price"]),
                    "max_price": summary["max_price"],
                    "max_price_text": format_price(summary["max_price"]),
                },
                "examples": examples,
                "center": center,
            },
            "state": {
                **state,
                "mode": "area_context",
                "lastDistrict": district,
                "lastNeighborhood": neighborhood,
            },
        })

    # -----------------------------------------------------
    # 3) GENEL YARDIM MESAJI
    # -----------------------------------------------------

    return jsonify({
        "reply": (
            "Bunu şu an iki şekilde kullanabilirsin:\n\n"
            "1) Ev ilanımı girmek istiyorum\n"
            "2) Kağıthane Hamidiye Mahallesi 3+1 ortalama ne kadar?\n\n"
            "Bir bölge seçtikten sonra sadece 'ortalama 3+1 evler ne kadar?' diye de sorabilirsin."
        ),
        "action": None,
        "data": None,
        "state": state,
    })


# ---------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "message": "Sayfa veya endpoint bulunamadı.",
    }), 404


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)