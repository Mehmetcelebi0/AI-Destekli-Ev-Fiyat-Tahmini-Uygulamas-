from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent
LISTINGS_PATH = BASE_DIR / "listings.json"
DISTRICT_CENTERS_PATH = BASE_DIR / "district_centers.json"


# =========================================================
# 1) GENEL YARDIMCI FONKSIYONLAR
# =========================================================

def load_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def safe_number(value: Any, default: Optional[float] = 0) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def format_price(price: Any) -> str:
    value = safe_number(price, 0) or 0
    return f"{int(round(value)):,}".replace(",", ".") + " TL"


def normalize_text(text: Any) -> str:
    value = str(text or "").lower().strip()

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
        value = value.replace(old, new)

    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_neighborhood(text: Any) -> str:
    value = normalize_text(text)
    value = value.replace(" mahallesi", "").strip()
    return value


def tokenize(message: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", normalize_text(message))


def has_any(text: str, keywords: List[str]) -> bool:
    normalized = normalize_text(text)

    for keyword in keywords:
        if normalize_text(keyword) in normalized:
            return True

    return False


def contains_word_or_phrase(message: str, phrase: str) -> bool:
    msg = normalize_text(message)
    target = normalize_text(phrase)

    if not target:
        return False

    pattern = r"(?<![a-z0-9])" + re.escape(target) + r"(?![a-z0-9])"
    return re.search(pattern, msg) is not None


def average(values: List[float]) -> float:
    valid = [v for v in values if v is not None and math.isfinite(v)]

    if not valid:
        return 0

    return sum(valid) / len(valid)


def median(values: List[float]) -> float:
    valid = [v for v in values if v is not None and math.isfinite(v)]

    if not valid:
        return 0

    return float(statistics.median(valid))


def get_listing_price(item: Dict[str, Any]) -> float:
    return safe_number(item.get("price"), 0) or 0


def get_listing_net_m2(item: Dict[str, Any]) -> float:
    return safe_number(item.get("net_metrekare"), 0) or 0


def get_listing_room(item: Dict[str, Any]) -> float:
    return safe_number(item.get("oda"), 0) or 0


def get_listing_salon(item: Dict[str, Any]) -> float:
    return safe_number(item.get("salon"), 0) or 0


def get_listing_m2_price(item: Dict[str, Any]) -> float:
    price = get_listing_price(item)
    net = get_listing_net_m2(item)

    if price <= 0 or net <= 0:
        return 0

    return price / net


# =========================================================
# 2) ORTAK VERI SINIFLARI
# =========================================================

@dataclass
class RoomInfo:
    oda: Optional[int] = None
    salon: Optional[int] = None

    def exists(self) -> bool:
        return self.oda is not None and self.salon is not None

    def text(self) -> str:
        if not self.exists():
            return ""
        return f"{self.oda}+{self.salon}"


@dataclass
class LocationInfo:
    district: Optional[str] = None
    neighborhood: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    def exists(self) -> bool:
        return bool(self.district)

    def text(self) -> str:
        if self.district and self.neighborhood:
            return f"{self.district} / {self.neighborhood}"

        if self.district:
            return self.district

        return "Bilinmeyen konum"


@dataclass
class PropertyInput:
    ilce: str = ""
    mahalle: str = ""
    net_metrekare: float = 0
    brut_metrekare: float = 0
    oda: float = 0
    salon: float = 0
    toplam_oda: float = 0
    binanin_yasi: str = ""
    binanin_kat_sayisi: float = 0
    bulundugu_kat_numeric: float = 0
    isitma_tipi: str = ""
    kullanim_durumu: Optional[float] = None
    krediye_uygunluk: Optional[float] = None
    tapu_durumu: str = ""
    site_icerisinde: Optional[float] = None
    banyo_sayisi: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PropertyInput":
        return cls(
            ilce=str(data.get("ilce") or ""),
            mahalle=str(data.get("mahalle") or ""),
            net_metrekare=safe_number(data.get("net_metrekare"), 0) or 0,
            brut_metrekare=safe_number(data.get("brut_metrekare"), 0) or 0,
            oda=safe_number(data.get("oda"), 0) or 0,
            salon=safe_number(data.get("salon"), 0) or 0,
            toplam_oda=safe_number(data.get("toplam_oda"), 0) or 0,
            binanin_yasi=str(data.get("binanin_yasi") or ""),
            binanin_kat_sayisi=safe_number(data.get("binanin_kat_sayisi"), 0) or 0,
            bulundugu_kat_numeric=safe_number(data.get("bulundugu_kat_numeric"), 0) or 0,
            isitma_tipi=str(data.get("isitma_tipi") or ""),
            kullanim_durumu=safe_number(data.get("kullanim_durumu"), None),
            krediye_uygunluk=safe_number(data.get("krediye_uygunluk"), None),
            tapu_durumu=str(data.get("tapu_durumu") or ""),
            site_icerisinde=safe_number(data.get("site_icerisinde"), None),
            banyo_sayisi=safe_number(data.get("banyo_sayisi"), None),
            raw=data,
        )

    def room_text(self) -> str:
        oda_text = int(self.oda) if float(self.oda).is_integer() else self.oda
        salon_text = int(self.salon) if float(self.salon).is_integer() else self.salon
        return f"{oda_text}+{salon_text}"

    def location_text(self) -> str:
        if self.ilce and self.mahalle:
            return f"{self.ilce} / {self.mahalle}"

        if self.ilce:
            return self.ilce

        return "Bilinmeyen konum"


# =========================================================
# 3) VERI HAVUZU
# =========================================================

class HouseAIDataStore:
    def __init__(self):
        self.listings = load_json(LISTINGS_PATH)
        self.centers = load_json(DISTRICT_CENTERS_PATH)

    def districts(self) -> List[str]:
        result = set()

        for item in self.listings:
            district = item.get("district")

            if district:
                result.add(district)

        return sorted(result)

    def neighborhoods(self, district: Optional[str] = None) -> List[str]:
        result = set()
        district_norm = normalize_text(district)

        for item in self.listings:
            if district and normalize_text(item.get("district")) != district_norm:
                continue

            neighborhood = item.get("neighborhood")

            if neighborhood:
                result.add(neighborhood)

        return sorted(result)

    def find_area_center(
        self,
        district: str,
        neighborhood: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        district_norm = normalize_text(district)
        neighborhood_norm = normalize_neighborhood(neighborhood)

        if neighborhood:
            for item in self.centers:
                if (
                    normalize_text(item.get("district")) == district_norm
                    and normalize_neighborhood(item.get("neighborhood")) == neighborhood_norm
                ):
                    return {
                        "district": item.get("district"),
                        "neighborhood": item.get("neighborhood"),
                        "lat": safe_number(item.get("lat")),
                        "lng": safe_number(item.get("lng")),
                    }

        for item in self.centers:
            if normalize_text(item.get("district")) == district_norm:
                return {
                    "district": item.get("district"),
                    "neighborhood": item.get("neighborhood"),
                    "lat": safe_number(item.get("lat")),
                    "lng": safe_number(item.get("lng")),
                }

        return None


# =========================================================
# 4) 1. SAYFA AI: HOUSEAI MAP AGENT
# =========================================================

class MapIntentDetector:
    @staticmethod
    def has_room_pattern(message: str) -> bool:
        text = normalize_text(message)
        return re.search(r"\d+\s*\+\s*\d+", text) is not None

    @staticmethod
    def looks_like_add_listing(message: str) -> Tuple[bool, int]:
        text = normalize_text(message)
        tokens = tokenize(message)

        score = 0

        direct_phrases = [
            "ev ilani girecegim",
            "ev ilanı gireceğim",
            "ev ilani girecem",
            "ev ilanı girecem",
            "ev ilanimi girmek",
            "ev ilanımı girmek",
            "ev ilani girmek",
            "ev ilanı girmek",
            "ev ilanimi girmek istiyorum",
            "ev ilanımı girmek istiyorum",
            "ilan girecegim",
            "ilan gireceğim",
            "ilan girecem",
            "ilan girmek istiyorum",
            "ilan eklemek istiyorum",
            "evimi satmak istiyorum",
            "evimi satacagim",
            "evimi satacağım",
            "satisa koymak istiyorum",
            "satışa koymak istiyorum",
            "konum secmek istiyorum",
            "konum seçmek istiyorum",
        ]

        if has_any(text, direct_phrases):
            score += 12

        has_ev = "ev" in tokens or "daire" in tokens or "konut" in tokens
        has_ilan = "ilan" in tokens or "ilani" in tokens or "ilanı" in tokens

        has_girme = any(
            token.startswith("gir")
            or token.startswith("gire")
            or token.startswith("ekle")
            or token.startswith("olustur")
            or token.startswith("oluştur")
            for token in tokens
        )

        has_satma = any(
            token.startswith("sat")
            or token.startswith("satis")
            or token.startswith("satış")
            for token in tokens
        )

        has_konum = "konum" in tokens or "lokasyon" in tokens
        has_secme = any(
            token.startswith("sec")
            or token.startswith("seç")
            or token.startswith("belirle")
            for token in tokens
        )

        if has_ev and has_ilan and has_girme:
            score += 12

        if has_ilan and has_girme:
            score += 9

        if has_ev and has_satma:
            score += 12

        if has_konum and has_secme:
            score += 8

        return score >= 6, score

    @staticmethod
    def looks_like_price_question(
        message: str,
        state: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, int]:
        text = normalize_text(message)
        state = state or {}
        context = context or {}

        score = 0

        price_keywords = [
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
            "kaça",
            "kaca",
            "tl",
            "kaç para",
            "kac para",
        ]

        if has_any(text, price_keywords):
            score += 7

        if MapIntentDetector.has_room_pattern(message):
            score += 4

        has_context_location = bool(
            state.get("lastDistrict")
            or context.get("district")
        )

        if has_context_location and MapIntentDetector.has_room_pattern(message):
            score += 7

        if has_context_location and re.fullmatch(r"\s*\d+\s*", text):
            score += 5

        return score >= 5, score

    @staticmethod
    def is_where_am_i(message: str) -> bool:
        phrases = [
            "neredeyim",
            "hangi mahalle",
            "hangi bolge",
            "hangi bölge",
            "secilen konum",
            "seçilen konum",
            "konumum ne",
        ]

        return has_any(message, phrases)

    @staticmethod
    def is_help(message: str) -> bool:
        phrases = [
            "yardim",
            "yardım",
            "ne yapabilirsin",
            "neler yapabilirsin",
            "komut",
            "ornek",
            "örnek",
        ]

        return has_any(message, phrases)

    @staticmethod
    def detect(
        message: str,
        state: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        text = normalize_text(message)
        state = state or {}
        context = context or {}

        if state.get("mode") == "add_listing":
            return "continue_flow"

        add_listing, add_score = MapIntentDetector.looks_like_add_listing(message)
        price_question, price_score = MapIntentDetector.looks_like_price_question(
            message,
            state,
            context,
        )

        if add_listing and add_score >= price_score:
            return "add_listing"

        if MapIntentDetector.is_where_am_i(message):
            return "where_am_i"

        if MapIntentDetector.is_help(message):
            return "help"

        if "en ucuz" in text or "ucuz" in text:
            return "cheapest"

        if (
            "en pahali" in text
            or "en pahalı" in text
            or "pahali" in text
            or "pahalı" in text
        ):
            return "expensive"

        if "firsat" in text or "fırsat" in text:
            return "opportunity"

        if price_question:
            return "market_summary"

        has_context_location = bool(
            state.get("lastDistrict")
            or context.get("district")
        )

        if has_context_location and len(text) <= 12:
            return "context_clarification"

        return "general"


class MapQueryParser:
    def __init__(self, store: HouseAIDataStore):
        self.store = store

    def extract_room(self, message: str, default_salon: int = 1) -> RoomInfo:
        text = normalize_text(message)

        match = re.search(r"(\d+)\s*\+\s*(\d+)", text)

        if match:
            return RoomInfo(
                oda=int(match.group(1)),
                salon=int(match.group(2)),
            )

        single_number = re.fullmatch(r"\s*(\d+)\s*", text)

        if single_number:
            return RoomInfo(
                oda=int(single_number.group(1)),
                salon=default_salon,
            )

        number_room = re.search(r"(\d+)\s*oda", text)

        if number_room:
            return RoomInfo(
                oda=int(number_room.group(1)),
                salon=default_salon,
            )

        return RoomInfo()

    def extract_location(self, message: str) -> LocationInfo:
        found_district = None
        found_neighborhood = None

        for district in sorted(self.store.districts(), key=len, reverse=True):
            if contains_word_or_phrase(message, district):
                found_district = district
                break

        candidate_neighborhoods = self.store.neighborhoods(found_district)

        for neighborhood in sorted(candidate_neighborhoods, key=len, reverse=True):
            full = neighborhood
            short = normalize_neighborhood(neighborhood)

            if contains_word_or_phrase(message, full) or contains_word_or_phrase(message, short):
                found_neighborhood = neighborhood
                break

        if found_neighborhood and not found_district:
            found_district = self.find_district_for_neighborhood(found_neighborhood)

        return LocationInfo(
            district=found_district,
            neighborhood=found_neighborhood,
        )

    def find_district_for_neighborhood(self, neighborhood: str) -> Optional[str]:
        target = normalize_neighborhood(neighborhood)

        for item in self.store.listings:
            if normalize_neighborhood(item.get("neighborhood")) == target:
                return item.get("district")

        return None

    def location_from_context(
        self,
        message: str,
        state: Dict[str, Any],
        context: Dict[str, Any],
    ) -> LocationInfo:
        location = self.extract_location(message)

        district = (
            location.district
            or state.get("lastDistrict")
            or state.get("district")
            or context.get("district")
        )

        neighborhood = (
            location.neighborhood
            or state.get("lastNeighborhood")
            or state.get("neighborhood")
            or context.get("neighborhood")
        )

        lat = context.get("lat") or state.get("selectedLat")
        lng = context.get("lng") or state.get("selectedLng")

        if neighborhood and not district:
            district = self.find_district_for_neighborhood(neighborhood)

        return LocationInfo(
            district=district,
            neighborhood=neighborhood,
            lat=safe_number(lat, None),
            lng=safe_number(lng, None),
        )


class MapMarketAnalyzer:
    def __init__(self, store: HouseAIDataStore):
        self.store = store

    def filter_listings(
        self,
        location: LocationInfo,
        room: RoomInfo,
    ) -> List[Dict[str, Any]]:
        district_norm = normalize_text(location.district)
        neighborhood_norm = normalize_neighborhood(location.neighborhood)

        result = []

        for item in self.store.listings:
            if location.district and normalize_text(item.get("district")) != district_norm:
                continue

            if location.neighborhood:
                if normalize_neighborhood(item.get("neighborhood")) != neighborhood_norm:
                    continue

            if room.exists():
                if int(get_listing_room(item)) != int(room.oda):
                    continue

                if int(get_listing_salon(item)) != int(room.salon):
                    continue

            if get_listing_price(item) <= 0 or get_listing_net_m2(item) <= 0:
                continue

            result.append(item)

        return result

    def summarize(self, listings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not listings:
            return None

        prices = [get_listing_price(item) for item in listings]
        m2_prices = [
            get_listing_m2_price(item)
            for item in listings
            if get_listing_m2_price(item) > 0
        ]

        return {
            "count": len(listings),
            "average_price": average(prices),
            "median_price": median(prices),
            "min_price": min(prices),
            "max_price": max(prices),
            "average_m2_price": average(m2_prices),
            "median_m2_price": median(m2_prices),
        }

    def examples(
        self,
        listings: List[Dict[str, Any]],
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        summary = self.summarize(listings)

        if not summary:
            return []

        avg_price = summary["average_price"]

        sorted_items = sorted(
            listings,
            key=lambda item: abs(get_listing_price(item) - avg_price),
        )

        if limit is not None:
            sorted_items = sorted_items[:limit]

        result = []

        for item in sorted_items:
            price = get_listing_price(item)
            net = get_listing_net_m2(item)
            predicted = safe_number(
                item.get("predictedPrice", item.get("predicted_price", 0)),
                0,
            ) or 0

            result.append({
                "id": item.get("id"),
                "title": item.get("title", "İlan"),
                "district": item.get("district"),
                "neighborhood": item.get("neighborhood"),
                "price": price,
                "price_text": format_price(price),
                "predicted_price": predicted,
                "predicted_price_text": format_price(predicted),
                "lat": safe_number(item.get("lat")),
                "lng": safe_number(item.get("lng")),
                "net_metrekare": net,
                "brut_metrekare": safe_number(item.get("brut_metrekare")),
                "oda": int(get_listing_room(item)),
                "salon": int(get_listing_salon(item)),
                "binanin_yasi": item.get("binanin_yasi"),
                "banyo_sayisi": int(safe_number(item.get("banyo_sayisi"), 0) or 0),
                "status": item.get("status", "normal"),
            })

        return result

    def center_for_result(
        self,
        location: LocationInfo,
        examples: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if examples:
            return {
                "lat": examples[0]["lat"],
                "lng": examples[0]["lng"],
                "zoom": 15,
            }

        center = self.store.find_area_center(location.district, location.neighborhood)

        if center:
            return {
                "lat": center["lat"],
                "lng": center["lng"],
                "zoom": 15,
            }

        return None


class HouseAIMapAgent:
    def __init__(self):
        self.store = HouseAIDataStore()
        self.parser = MapQueryParser(self.store)
        self.analyzer = MapMarketAnalyzer(self.store)

    def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = payload.get("message", "")
        state = payload.get("state", {}) or {}
        context = payload.get("context", {}) or {}

        intent = MapIntentDetector.detect(message, state, context)

        if not self.store.listings:
            return self.response(
                reply="İlan verisi bulunamadı. listings.json dosyasını kontrol et.",
                state=state,
            )

        if state.get("mode") == "add_listing" or intent == "continue_flow":
            return self.handle_add_listing_flow(message, state)

        if intent == "add_listing":
            return self.start_add_listing_flow()

        if intent == "where_am_i":
            return self.where_am_i(state, context)

        if intent == "help":
            return self.help_reply(state)

        if intent in ["market_summary", "cheapest", "expensive", "opportunity"]:
            return self.market_reply(message, state, context, intent)

        if intent == "context_clarification":
            district = state.get("lastDistrict") or context.get("district")
            neighborhood = state.get("lastNeighborhood") or context.get("neighborhood")

            return self.response(
                reply=(
                    f"Şu an seçili bölge <strong>{district} / {neighborhood}</strong> görünüyor.<br><br>"
                    f"Fiyat analizi istiyorsan şöyle yazabilirsin:<br>"
                    f"• <strong>ortalama 2+1 ne kadar?</strong><br>"
                    f"• <strong>en ucuz 2+1 ilanları göster</strong><br>"
                    f"• <strong>fırsat ilanları göster</strong><br><br>"
                    f"İlan girmek istiyorsan <strong>ev ilanı gireceğim</strong> yazman yeterli."
                ),
                state=state,
            )

        return self.response(
            reply=(
                "Seni tam olarak anlayamadım ama yardımcı olabilirim.<br><br>"
                "Şunlardan birini yazabilirsin:<br>"
                "1) <strong>Ev ilanımı girmek istiyorum</strong><br>"
                "2) <strong>Kağıthane Hamidiye Mahallesi 3+1 ortalama ne kadar?</strong><br>"
                "3) Konum seçtikten sonra <strong>ortalama 2+1 ne kadar?</strong><br>"
                "4) <strong>en ucuz 2+1 ilanları göster</strong><br>"
                "5) <strong>fırsat ilanları göster</strong>"
            ),
            state=state,
        )

    def start_add_listing_flow(self) -> Dict[str, Any]:
        return self.response(
            reply=(
                "Tabii, ev ilanını girmek için yardımcı olayım. "
                "Önce ilçeyi yazar mısın? Örnek: <strong>Kağıthane</strong>"
            ),
            state={
                "mode": "add_listing",
                "step": "ask_district",
            },
        )

    def handle_add_listing_flow(
        self,
        message: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        step = state.get("step")

        if step == "ask_district":
            district = self.find_district_in_text(message)

            if not district:
                return self.response(
                    reply=(
                        "İlçeyi tam anlayamadım. "
                        "Örnek: <strong>Kağıthane</strong>, <strong>Kadıköy</strong>, <strong>Beşiktaş</strong>."
                    ),
                    state=state,
                )

            return self.response(
                reply=(
                    f"Tamam, ilçe: <strong>{district}</strong>. "
                    f"Şimdi mahallenin adını yazar mısın? Örnek: <strong>Hamidiye Mahallesi</strong>"
                ),
                state={
                    "mode": "add_listing",
                    "step": "ask_neighborhood",
                    "district": district,
                    "lastDistrict": district,
                },
            )

        if step == "ask_neighborhood":
            district = state.get("district") or state.get("lastDistrict")
            neighborhood = self.find_neighborhood_in_text(message, district)

            if not neighborhood:
                return self.response(
                    reply=(
                        "Mahalle adını tam anlayamadım. "
                        "Örnek: <strong>Hamidiye Mahallesi</strong>, <strong>Merkez</strong>, <strong>Talatpaşa</strong>."
                    ),
                    state=state,
                )

            center = self.store.find_area_center(district, neighborhood)

            if not center:
                return self.response(
                    reply=f"{district} / {neighborhood} için harita merkezi bulamadım.",
                    state={
                        "mode": "area_context",
                        "lastDistrict": district,
                        "lastNeighborhood": neighborhood,
                    },
                )

            return self.response(
                reply=(
                    f"Süper. Haritayı <strong>{district} / {neighborhood}</strong> bölgesine götürüyorum. "
                    f"Haritada evinin tam konumuna tıkla."
                ),
                action="fly_to_area_and_select",
                data={
                    "district": district,
                    "neighborhood": neighborhood,
                    "lat": center["lat"],
                    "lng": center["lng"],
                    "zoom": 16,
                },
                state={
                    "mode": "area_context",
                    "lastDistrict": district,
                    "lastNeighborhood": neighborhood,
                },
            )

        return self.start_add_listing_flow()

    def market_reply(
        self,
        message: str,
        state: Dict[str, Any],
        context: Dict[str, Any],
        intent: str,
    ) -> Dict[str, Any]:
        location = self.parser.location_from_context(message, state, context)
        room = self.parser.extract_room(message)

        if not location.district:
            return self.response(
                reply=(
                    "Hangi ilçe için fiyat analizi istediğini anlayamadım.<br>"
                    "Örnek: <strong>Kağıthane Hamidiye Mahallesi 3+1 ortalama ne kadar?</strong><br><br>"
                    "Bir konum seçtiysen sayfayı yenileyip tekrar deneyebilirsin."
                ),
                state=state,
            )

        listings = self.analyzer.filter_listings(location, room)

        if intent == "opportunity":
            listings = [item for item in listings if item.get("status") == "opportunity"]

        if intent == "cheapest":
            listings = sorted(listings, key=lambda item: get_listing_price(item))

        if intent == "expensive":
            listings = sorted(
                listings,
                key=lambda item: get_listing_price(item),
                reverse=True,
            )

        if not listings:
            room_text = f" {room.text()}" if room.exists() else ""

            return self.response(
                reply=(
                    f"<strong>{location.text()}{room_text}</strong> için uygun ilan bulunamadı.<br><br>"
                    f"Seçili mahalle varsa tüm ilçeye genişletmedim. "
                    f"Böylece kullanıcıya yanlış bölge sonucu göstermiyoruz."
                ),
                action="show_market_result",
                data={
                    "district": location.district,
                    "neighborhood": location.neighborhood,
                    "oda": room.oda,
                    "salon": room.salon,
                    "summary": None,
                    "examples": [],
                    "center": self.analyzer.center_for_result(location, []),
                },
                state={
                    **state,
                    "mode": "area_context",
                    "lastDistrict": location.district,
                    "lastNeighborhood": location.neighborhood,
                },
            )

        summary = self.analyzer.summarize(listings)
        examples = self.analyzer.examples(listings, limit=None)

        if intent == "cheapest":
            reply = self.cheapest_reply(location, room, summary)
        elif intent == "expensive":
            reply = self.expensive_reply(location, room, summary)
        elif intent == "opportunity":
            reply = self.opportunity_reply(location, room, summary)
        else:
            reply = self.summary_reply(location, room, summary)

        return self.response(
            reply=reply,
            action="show_market_result",
            data={
                "district": location.district,
                "neighborhood": location.neighborhood,
                "oda": room.oda,
                "salon": room.salon,
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
                "center": self.analyzer.center_for_result(location, examples),
            },
            state={
                **state,
                "mode": "area_context",
                "lastDistrict": location.district,
                "lastNeighborhood": location.neighborhood,
            },
        )

    def summary_reply(
        self,
        location: LocationInfo,
        room: RoomInfo,
        summary: Dict[str, Any],
    ) -> str:
        room_text = f" {room.text()}" if room.exists() else ""

        return (
            f"<strong>{location.text()}{room_text}</strong> ilanları için piyasa özeti:<br><br>"
            f"Ortalama fiyat: <strong>{format_price(summary['average_price'])}</strong><br>"
            f"Medyan fiyat: <strong>{format_price(summary['median_price'])}</strong><br>"
            f"Ortalama m² fiyatı: <strong>{format_price(summary['average_m2_price'])}</strong><br>"
            f"İlan sayısı: <strong>{summary['count']}</strong><br>"
            f"Fiyat aralığı: <strong>{format_price(summary['min_price'])} - {format_price(summary['max_price'])}</strong>"
        )

    def cheapest_reply(
        self,
        location: LocationInfo,
        room: RoomInfo,
        summary: Dict[str, Any],
    ) -> str:
        room_text = f" {room.text()}" if room.exists() else ""

        return (
            f"<strong>{location.text()}{room_text}</strong> için en ucuz ilanları listeledim.<br><br>"
            f"En düşük fiyat: <strong>{format_price(summary['min_price'])}</strong><br>"
            f"Ortalama fiyat: <strong>{format_price(summary['average_price'])}</strong><br>"
            f"İlan sayısı: <strong>{summary['count']}</strong>"
        )

    def expensive_reply(
        self,
        location: LocationInfo,
        room: RoomInfo,
        summary: Dict[str, Any],
    ) -> str:
        room_text = f" {room.text()}" if room.exists() else ""

        return (
            f"<strong>{location.text()}{room_text}</strong> için en pahalı ilanları listeledim.<br><br>"
            f"En yüksek fiyat: <strong>{format_price(summary['max_price'])}</strong><br>"
            f"Medyan fiyat: <strong>{format_price(summary['median_price'])}</strong><br>"
            f"Bu ilanlar üst fiyat bandını temsil eder."
        )

    def opportunity_reply(
        self,
        location: LocationInfo,
        room: RoomInfo,
        summary: Dict[str, Any],
    ) -> str:
        room_text = f" {room.text()}" if room.exists() else ""

        return (
            f"<strong>{location.text()}{room_text}</strong> için fırsat ilanlarını listeledim.<br><br>"
            f"Fırsat ilanı sayısı: <strong>{summary['count']}</strong><br>"
            f"Ortalama fırsat fiyatı: <strong>{format_price(summary['average_price'])}</strong>"
        )

    def where_am_i(
        self,
        state: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        district = state.get("lastDistrict") or context.get("district")
        neighborhood = state.get("lastNeighborhood") or context.get("neighborhood")

        if not district:
            return self.response(
                reply="Henüz seçili bir konum görünmüyor. Önce haritadan konum seçebilirsin.",
                state=state,
            )

        return self.response(
            reply=f"Şu an seçili bölge: <strong>{district} / {neighborhood}</strong>",
            state=state,
        )

    def help_reply(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.response(
            reply=(
                "Ben HouseAI Map Agent olarak şunları yapabilirim:<br><br>"
                "• Mahalle bazlı ortalama fiyat analizi<br>"
                "• Oda tipine göre ilan listeleme<br>"
                "• En ucuz / en pahalı ilanları bulma<br>"
                "• Fırsat ilanlarını gösterme<br>"
                "• Haritada ev konumu seçtirme<br>"
                "• Seçili mahalleyi hatırlama<br><br>"
                "Örnek: <strong>ortalama 2+1 ne kadar?</strong>"
            ),
            state=state,
        )

    def find_district_in_text(self, message: str) -> Optional[str]:
        for district in sorted(self.store.districts(), key=len, reverse=True):
            if contains_word_or_phrase(message, district):
                return district

        return None

    def find_neighborhood_in_text(
        self,
        message: str,
        district: Optional[str],
    ) -> Optional[str]:
        for neighborhood in sorted(self.store.neighborhoods(district), key=len, reverse=True):
            if contains_word_or_phrase(message, neighborhood) or contains_word_or_phrase(message, normalize_neighborhood(neighborhood)):
                return neighborhood

        return None

    def response(
        self,
        reply: str,
        state: Dict[str, Any],
        action: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "reply": reply,
            "action": action,
            "data": data,
            "state": state,
        }


# =========================================================
# 5) 3. SAYFA AI: HOUSEAI SELLER AGENT
# =========================================================

class SellerScenarioParser:
    @staticmethod
    def parse_price(message: str) -> Optional[float]:
        text = normalize_text(message)

        match_million = re.search(r"(\d+(?:[.,]\d+)?)\s*(milyon|m|mn)", text)

        if match_million:
            value = float(match_million.group(1).replace(",", "."))
            return value * 1_000_000

        numbers = re.findall(r"\d+", text)

        if numbers:
            combined = "".join(numbers)

            if len(combined) >= 6:
                return float(combined)

        return None


class SellerIntentDetector:
    @staticmethod
    def detect(message: str) -> str:
        text = normalize_text(message)

        requested_price = SellerScenarioParser.parse_price(message)

        if requested_price:
            return "price_scenario"

        if "hizli" in text or "hızlı" in text or "acil" in text or "hemen" in text:
            return "quick_sale"

        if "yuksek" in text or "yüksek" in text or "pahali" in text or "pahalı" in text:
            return "high_sale"

        if "normal" in text or "dengeli" in text or "makul" in text:
            return "balanced_sale"

        if "6 ay" in text or "gelecek" in text or "sonra" in text:
            return "future_price"

        if "ilan" in text and (
            "aciklama" in text
            or "açıklama" in text
            or "baslik" in text
            or "başlık" in text
            or "metin" in text
        ):
            return "listing_copy"

        if "benzer" in text or "emsal" in text or "karsilastir" in text or "karşılaştır" in text:
            return "similar_listings"

        if "nasil hesap" in text or "nasıl hesap" in text or "neden" in text or "formul" in text or "formül" in text:
            return "calculation_explain"

        if "rapor" in text or "detayli analiz" in text or "detaylı analiz" in text:
            return "report"

        if "eksik" in text or "ne lazim" in text or "ne lazım" in text:
            return "missing_fields"

        if "pazarlik" in text or "pazarlık" in text or "teklif" in text or "son fiyat" in text:
            return "negotiation"

        if "risk" in text or "satilmazsa" in text or "satılmazsa" in text or "beklerse" in text:
            return "risk"

        if "30 gun" in text or "30 gün" in text or "satis plani" in text or "satış planı" in text:
            return "sales_plan"

        if "alici gozu" in text or "alıcı gözü" in text or "alici" in text or "alıcı" in text:
            return "buyer_perspective"

        if "piyasa" in text or "istanbul" in text or "konut" in text:
            return "market_commentary"

        if "yardim" in text or "yardım" in text or "ne yapabilirsin" in text:
            return "help"

        return "general"


class SellerComparableAnalyzer:
    def __init__(self, store: HouseAIDataStore):
        self.store = store

    def find_similar(self, prop: PropertyInput) -> Dict[str, Any]:
        valid = [
            item for item in self.store.listings
            if get_listing_price(item) > 0 and get_listing_net_m2(item) > 0
        ]

        strong = [
            item for item in valid
            if self.same_district(item, prop)
            and self.same_neighborhood(item, prop)
            and self.same_room(item, prop)
            and self.similar_m2(item, prop)
        ]

        if len(strong) >= 3:
            return self.result(
                strong,
                "Aynı mahalle + aynı oda tipi + benzer m²",
                "Yüksek" if len(strong) >= 6 else "Orta-Yüksek",
            )

        neighborhood_room = [
            item for item in valid
            if self.same_district(item, prop)
            and self.same_neighborhood(item, prop)
            and self.same_room(item, prop)
        ]

        if len(neighborhood_room) >= 2:
            return self.result(
                neighborhood_room,
                "Aynı mahalle + aynı oda tipi",
                "Orta-Yüksek",
            )

        neighborhood_all = [
            item for item in valid
            if self.same_district(item, prop)
            and self.same_neighborhood(item, prop)
        ]

        if len(neighborhood_all) >= 2:
            return self.result(
                neighborhood_all,
                "Aynı mahalle tüm oda tipleri",
                "Orta",
            )

        district_room = [
            item for item in valid
            if self.same_district(item, prop)
            and self.same_room(item, prop)
        ]

        if len(district_room) >= 2:
            return self.result(
                district_room,
                "Aynı ilçe + aynı oda tipi",
                "Düşük-Orta",
            )

        district_all = [
            item for item in valid
            if self.same_district(item, prop)
        ]

        return self.result(
            district_all,
            "Aynı ilçe genel veri",
            "Düşük",
        )

    def same_district(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        return normalize_text(item.get("district")) == normalize_text(prop.ilce)

    def same_neighborhood(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        return normalize_neighborhood(item.get("neighborhood")) == normalize_neighborhood(prop.mahalle)

    def same_room(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        return get_listing_room(item) == prop.oda and get_listing_salon(item) == prop.salon

    def similar_m2(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        if prop.net_metrekare <= 0:
            return True

        item_m2 = get_listing_net_m2(item)

        return prop.net_metrekare * 0.75 <= item_m2 <= prop.net_metrekare * 1.25

    def result(
        self,
        items: List[Dict[str, Any]],
        match_level: str,
        confidence: str,
    ) -> Dict[str, Any]:
        items = sorted(items, key=lambda item: get_listing_price(item))

        prices = [get_listing_price(item) for item in items]
        m2_prices = [
            get_listing_m2_price(item)
            for item in items
            if get_listing_m2_price(item) > 0
        ]

        return {
            "items": items,
            "count": len(items),
            "match_level": match_level,
            "confidence": confidence,
            "average_price": average(prices),
            "median_price": median(prices),
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "average_m2_price": average(m2_prices),
            "median_m2_price": median(m2_prices),
            "examples": self.examples(items[:8]),
        }

    def examples(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []

        for item in items:
            price = get_listing_price(item)
            net = get_listing_net_m2(item)
            m2_price = price / net if net else 0

            result.append({
                "title": item.get("title", "Benzer ilan"),
                "district": item.get("district"),
                "neighborhood": item.get("neighborhood"),
                "price": price,
                "price_text": format_price(price),
                "net_metrekare": net,
                "brut_metrekare": safe_number(item.get("brut_metrekare"), 0),
                "oda": get_listing_room(item),
                "salon": get_listing_salon(item),
                "m2_price": round(m2_price),
                "m2_price_text": format_price(m2_price),
                "lat": safe_number(item.get("lat"), 0),
                "lng": safe_number(item.get("lng"), 0),
            })

        return result


@dataclass
class SellerStrategy:
    estimated_price: float
    quick_sale_price: float
    balanced_sale_price: float
    high_sale_price: float
    six_month_prediction: float
    confidence: str
    match_level: str
    similar_count: int
    average_price: float
    median_price: float
    average_m2_price: float
    median_m2_price: float
    min_price: float
    max_price: float


class SellerStrategyEngine:
    def build(
        self,
        prop: PropertyInput,
        prediction_result: Dict[str, Any],
        comparable: Dict[str, Any],
    ) -> SellerStrategy:
        estimated = self.estimated_price(prop, prediction_result, comparable)

        quick = estimated * 0.96
        balanced = estimated * 1.02
        high = estimated * 1.08
        six_month = estimated * self.future_multiplier(comparable)

        return SellerStrategy(
            estimated_price=estimated,
            quick_sale_price=quick,
            balanced_sale_price=balanced,
            high_sale_price=high,
            six_month_prediction=six_month,
            confidence=comparable.get("confidence", "Orta"),
            match_level=comparable.get("match_level", "Bilinmiyor"),
            similar_count=comparable.get("count", 0),
            average_price=comparable.get("average_price", 0),
            median_price=comparable.get("median_price", 0),
            average_m2_price=comparable.get("average_m2_price", 0),
            median_m2_price=comparable.get("median_m2_price", 0),
            min_price=comparable.get("min_price", 0),
            max_price=comparable.get("max_price", 0),
        )

    def estimated_price(
        self,
        prop: PropertyInput,
        prediction_result: Dict[str, Any],
        comparable: Dict[str, Any],
    ) -> float:
        if prediction_result and prediction_result.get("success") and prediction_result.get("prediction"):
            value = safe_number(
                prediction_result["prediction"].get("estimated_price"),
                None,
            )

            if value and value > 0:
                return value

        base_m2 = comparable.get("median_m2_price") or comparable.get("average_m2_price") or 0
        estimated = base_m2 * prop.net_metrekare

        if estimated <= 0:
            estimated = comparable.get("median_price") or comparable.get("average_price") or 0

        return self.apply_adjustments(estimated, prop)

    def apply_adjustments(self, price: float, prop: PropertyInput) -> float:
        value = float(price)

        if prop.site_icerisinde == 1:
            value *= 1.03

        if prop.krediye_uygunluk == 2:
            value *= 1.02

        if "kat mulkiyeti" in normalize_text(prop.tapu_durumu):
            value *= 1.015

        heating = normalize_text(prop.isitma_tipi)

        if "merkezi" in heating or "yerden" in heating:
            value *= 1.015

        if prop.banyo_sayisi and prop.banyo_sayisi >= 2:
            value *= 1.015

        if prop.binanin_kat_sayisi and prop.bulundugu_kat_numeric:
            ratio = prop.bulundugu_kat_numeric / prop.binanin_kat_sayisi

            if 0.25 <= ratio <= 0.75:
                value *= 1.01

        return value

    def future_multiplier(self, comparable: Dict[str, Any]) -> float:
        confidence = comparable.get("confidence", "")

        if confidence == "Yüksek":
            return 1.04

        if confidence == "Orta-Yüksek":
            return 1.035

        if confidence == "Orta":
            return 1.03

        return 1.02


class SellerResponseBuilder:
    def __init__(
        self,
        prop: PropertyInput,
        strategy: SellerStrategy,
        comparable: Dict[str, Any],
        prediction_result: Dict[str, Any],
    ):
        self.prop = prop
        self.strategy = strategy
        self.comparable = comparable
        self.prediction_result = prediction_result or {}

    def quick_sale(self) -> str:
        return (
            f"Hızlı satış için önerim: <strong>{format_price(self.strategy.quick_sale_price)}</strong><br><br>"
            f"Bu fiyat, tahmini piyasa değerinin biraz altında konumlanır. "
            f"Amaç daha fazla alıcı ilgisi almak ve ilanın bekleme süresini azaltmaktır.<br><br>"
            f"Bu stratejide pazarlık payı daha sınırlı olur ama satış hızı artabilir."
        )

    def high_sale(self) -> str:
        return (
            f"Yüksekten deneme fiyatı: <strong>{format_price(self.strategy.high_sale_price)}</strong><br><br>"
            f"Bu fiyat pazarlık payı bırakır. Ancak satış süresi uzayabilir. "
            f"İlk 2-4 hafta talep düşük kalırsa fiyatı "
            f"<strong>{format_price(self.strategy.balanced_sale_price)}</strong> bandına çekmek mantıklı olur."
        )

    def balanced_sale(self) -> str:
        return (
            f"Dengeli satış fiyatı: <strong>{format_price(self.strategy.balanced_sale_price)}</strong><br><br>"
            f"Bu fiyat hem satıcıyı korur hem de alıcı tarafında gerçekçi görünür. "
            f"Benim ana önerim bu bandı başlangıç fiyatı olarak kullanman."
        )

    def future_price(self) -> str:
        return (
            f"6 ay sonrası basit tahmin: <strong>{format_price(self.strategy.six_month_prediction)}</strong><br><br>"
            f"Bu tahmin mevcut veri ve kısa dönem fiyat eğilimi varsayımıyla üretilmiştir. "
            f"Canlı piyasa/haber verisi bağlandığında daha güçlü hale gelir."
        )

    def listing_copy(self) -> str:
        return (
            f"<strong>Başlık önerileri:</strong><br>"
            f"1. {self.prop.mahalle} Bölgesinde {self.prop.room_text()} Satılık Daire<br>"
            f"2. {self.prop.ilce}'de {int(self.prop.net_metrekare)} m² Net Kullanımlı Satılık Daire<br>"
            f"3. {self.prop.mahalle}'nde Merkezi Konumda Satılık {self.prop.room_text()} Daire<br><br>"
            f"<strong>İlan açıklaması:</strong><br>"
            f"{self.prop.ilce} {self.prop.mahalle} bölgesinde yer alan bu {self.prop.room_text()} daire, "
            f"{int(self.prop.net_metrekare)} m² net ve {int(self.prop.brut_metrekare)} m² brüt kullanım alanı sunmaktadır. "
            f"{self.prop.binanin_yasi} yaş aralığındaki binada bulunan daire, "
            f"{self.prop.isitma_tipi or 'belirtilen ısıtma tipi'} ile ısınmaktadır. "
            f"HouseAI analizine göre dengeli ilan fiyatı yaklaşık "
            f"<strong>{format_price(self.strategy.balanced_sale_price)}</strong> seviyesindedir."
        )

    def similar_listings(self) -> str:
        examples = self.comparable.get("examples", [])

        if not examples:
            return "Benzer ilan bulunamadı. Bu yüzden tahmin güveni düşük."

        lines = [
            f"Bu analizde <strong>{self.strategy.similar_count}</strong> benzer ilan kullanıldı.",
            f"Karşılaştırma seviyesi: <strong>{self.strategy.match_level}</strong>",
            f"Tahmin güveni: <strong>{self.strategy.confidence}</strong>",
            "",
            f"Ortalama fiyat: <strong>{format_price(self.strategy.average_price)}</strong>",
            f"Medyan fiyat: <strong>{format_price(self.strategy.median_price)}</strong>",
            f"Ortalama m² fiyatı: <strong>{format_price(self.strategy.average_m2_price)}</strong>",
            "",
            "Örnek emsal ilanlar:",
        ]

        for index, item in enumerate(examples[:6], start=1):
            lines.append(
                f"{index}) {item.get('neighborhood', '-')}, "
                f"{item.get('oda', '-') }+{item.get('salon', '-')}, "
                f"{item.get('net_metrekare', '-') } m² → "
                f"<strong>{item.get('price_text')}</strong>"
            )

        return "<br>".join(lines)

    def calculation_explain(self) -> str:
        model_type = self.prediction_result.get("model_type", "trained/fallback estimator")

        return (
            f"Hesaplama mantığı:<br><br>"
            f"1. Önce 2. sayfadaki ev bilgileri okundu.<br>"
            f"2. {self.prop.location_text()} bölgesindeki benzer ilanlar bulundu.<br>"
            f"3. Aynı mahalle, oda tipi ve metrekareye yakın ilanlar önceliklendirildi.<br>"
            f"4. Model tahmini varsa model sonucu kullanıldı; yoksa emsal m² fiyatından tahmin üretildi.<br>"
            f"5. Tapu, kredi, site, ısıtma, banyo ve kat bilgisi gibi özellikler küçük düzeltme olarak uygulandı.<br><br>"
            f"Kullanılan model: <strong>{model_type}</strong><br>"
            f"Son tahmini değer: <strong>{format_price(self.strategy.estimated_price)}</strong>"
        )

    def report(self) -> str:
        return (
            f"<strong>HouseAI Seller Satış Raporu</strong><br><br>"
            f"Bölge: <strong>{self.prop.location_text()}</strong><br>"
            f"Ev tipi: <strong>{self.prop.room_text()}</strong><br>"
            f"Net m²: <strong>{self.prop.net_metrekare}</strong><br>"
            f"Brüt m²: <strong>{self.prop.brut_metrekare}</strong><br>"
            f"Bina yaşı: <strong>{self.prop.binanin_yasi}</strong><br>"
            f"Kat: <strong>{self.prop.bulundugu_kat_numeric}/{self.prop.binanin_kat_sayisi}</strong><br><br>"
            f"Tahmini piyasa değeri: <strong>{format_price(self.strategy.estimated_price)}</strong><br>"
            f"Hızlı satış fiyatı: <strong>{format_price(self.strategy.quick_sale_price)}</strong><br>"
            f"Dengeli fiyat: <strong>{format_price(self.strategy.balanced_sale_price)}</strong><br>"
            f"Yüksekten deneme: <strong>{format_price(self.strategy.high_sale_price)}</strong><br>"
            f"6 ay sonrası tahmin: <strong>{format_price(self.strategy.six_month_prediction)}</strong><br><br>"
            f"Benzer ilan sayısı: <strong>{self.strategy.similar_count}</strong><br>"
            f"Karşılaştırma seviyesi: <strong>{self.strategy.match_level}</strong><br>"
            f"Güven: <strong>{self.strategy.confidence}</strong>"
        )

    def missing_fields(self) -> str:
        missing = []

        checks = [
            ("İlçe", self.prop.ilce),
            ("Mahalle", self.prop.mahalle),
            ("Net m²", self.prop.net_metrekare),
            ("Brüt m²", self.prop.brut_metrekare),
            ("Oda", self.prop.oda),
            ("Salon", self.prop.salon),
            ("Bina yaşı", self.prop.binanin_yasi),
            ("Kat bilgisi", self.prop.bulundugu_kat_numeric),
            ("Isıtma tipi", self.prop.isitma_tipi),
            ("Tapu durumu", self.prop.tapu_durumu),
            ("Banyo sayısı", self.prop.banyo_sayisi),
        ]

        for label, value in checks:
            if value is None or value == "" or value == 0:
                missing.append(label)

        if not missing:
            return "Temel alanların çoğu dolu görünüyor. Tahmin için veri yeterli."

        return "Şu bilgiler eksik veya zayıf görünüyor:<br><br>" + "<br>".join([f"• {item}" for item in missing])

    def negotiation(self) -> str:
        low = self.strategy.estimated_price * 0.99
        high = self.strategy.estimated_price * 1.03

        return (
            f"Pazarlık stratejisi:<br><br>"
            f"İlanı <strong>{format_price(self.strategy.high_sale_price)}</strong> civarında açarsan pazarlık payı bırakmış olursun.<br><br>"
            f"Makul kapanış aralığı: <strong>{format_price(low)} - {format_price(high)}</strong><br><br>"
            f"Alıcı ciddi ise önce emsal fiyatlar ve evin güçlü yanları savunulmalı, sonra kontrollü indirim yapılmalı."
        )

    def risk(self) -> str:
        return (
            f"Satış riski analizi:<br><br>"
            f"• Hızlı fiyat düşük risklidir, daha hızlı talep getirir.<br>"
            f"• Dengeli fiyat orta risklidir, en mantıklı başlangıçtır.<br>"
            f"• Yüksekten fiyat daha risklidir, satış süresini uzatabilir.<br><br>"
            f"Yüksekten başlanırsa 2-4 hafta performans izlenmeli."
        )

    def sales_plan(self) -> str:
        return (
            f"<strong>30 Günlük Satış Planı</strong><br><br>"
            f"1. Hafta: İlanı <strong>{format_price(self.strategy.balanced_sale_price)}</strong> bandında yayına al.<br>"
            f"2. Hafta: Görüntülenme düşükse başlık ve ilk fotoğrafı değiştir.<br>"
            f"3. Hafta: Talep yoksa fiyatı hızlı satış bandına yaklaştır: <strong>{format_price(self.strategy.quick_sale_price)}</strong>.<br>"
            f"4. Hafta: Hâlâ dönüş yoksa emsal ilanlar tekrar kontrol edilmeli ve açıklama güncellenmeli."
        )

    def buyer_perspective(self) -> str:
        return (
            f"Alıcı gözünden değerlendirme:<br><br>"
            f"Bu ev <strong>{format_price(self.strategy.balanced_sale_price)}</strong> bandında daha gerçekçi görünür. "
            f"Fiyat <strong>{format_price(self.strategy.high_sale_price)}</strong> seviyesine çıkarsa alıcı pazarlık bekler ve karar süresi uzar. "
            f"İlan açıklamasında net m², konum, kredi uygunluğu ve ulaşım avantajları güçlü vurgulanmalı."
        )

    def market_commentary(self) -> str:
        return (
            f"{self.prop.location_text()} bölgesi için veri bazlı piyasa yorumu:<br><br>"
            f"Benzer ilan sayısı: <strong>{self.strategy.similar_count}</strong><br>"
            f"Ortalama fiyat: <strong>{format_price(self.strategy.average_price)}</strong><br>"
            f"Ortalama m² fiyatı: <strong>{format_price(self.strategy.average_m2_price)}</strong><br><br>"
            f"Bu verilere göre evin dengeli satış bandı "
            f"<strong>{format_price(self.strategy.balanced_sale_price)}</strong> seviyesidir."
        )

    def price_scenario(self, requested_price: float) -> str:
        diff = requested_price - self.strategy.estimated_price
        diff_percent = diff / self.strategy.estimated_price * 100 if self.strategy.estimated_price else 0

        if diff_percent > 8:
            comment = "Bu fiyat oldukça yüksek kalıyor. Satış süresi uzayabilir."
        elif diff_percent > 3:
            comment = "Bu fiyat pazarlık payı için denenebilir ama talep dikkatle izlenmeli."
        elif diff_percent >= -3:
            comment = "Bu fiyat tahmini piyasa değerine yakın ve dengeli görünüyor."
        else:
            comment = "Bu fiyat hızlı satış için güçlü olabilir ama pazarlık payını azaltır."

        return (
            f"<strong>{format_price(requested_price)}</strong> senaryo analizi:<br><br>"
            f"Tahmini piyasa değeri: <strong>{format_price(self.strategy.estimated_price)}</strong><br>"
            f"Fark: <strong>{diff_percent:.1f}%</strong><br><br>"
            f"{comment}"
        )

    def help(self) -> str:
        return (
            f"Ben HouseAI Seller olarak şunları yapabilirim:<br><br>"
            f"• Hızlı / dengeli / yüksek satış fiyatı öneririm<br>"
            f"• Benzer ilanları analiz ederim<br>"
            f"• İlan açıklaması yazarım<br>"
            f"• Pazarlık stratejisi çıkarırım<br>"
            f"• 30 günlük satış planı oluştururum<br>"
            f"• Alıcı gözünden yorum yaparım<br>"
            f"• Fiyat senaryosu analiz ederim<br><br>"
            f"Örnek: <strong>9.5 milyona koysam mantıklı mı?</strong>"
        )

    def general(self) -> str:
        return (
            f"Şu anki ana önerim:<br><br>"
            f"• Tahmini değer: <strong>{format_price(self.strategy.estimated_price)}</strong><br>"
            f"• Hızlı satış: <strong>{format_price(self.strategy.quick_sale_price)}</strong><br>"
            f"• Dengeli fiyat: <strong>{format_price(self.strategy.balanced_sale_price)}</strong><br>"
            f"• Yüksekten deneme: <strong>{format_price(self.strategy.high_sale_price)}</strong><br><br>"
            f"Daha detaylı analiz için <strong>rapor oluştur</strong>, "
            f"<strong>ilan açıklaması yaz</strong> veya "
            f"<strong>9.5 milyona koysam mantıklı mı?</strong> yazabilirsin."
        )


class HouseAISellerAgent:
    def __init__(self):
        self.store = HouseAIDataStore()
        self.comparable_analyzer = SellerComparableAnalyzer(self.store)
        self.strategy_engine = SellerStrategyEngine()

    def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = payload.get("message", "")
        model_input_data = payload.get("modelInput") or {}
        prediction_result = payload.get("predictionResult") or {}

        if not model_input_data:
            return {
                "success": False,
                "reply": "Önce 2. sayfada ev bilgilerini hazırlaman gerekiyor.",
                "intent": "missing_input",
            }

        prop = PropertyInput.from_dict(model_input_data)
        comparable = self.comparable_analyzer.find_similar(prop)
        strategy = self.strategy_engine.build(prop, prediction_result, comparable)
        builder = SellerResponseBuilder(prop, strategy, comparable, prediction_result)

        intent = SellerIntentDetector.detect(message)

        if intent == "quick_sale":
            reply = builder.quick_sale()
        elif intent == "high_sale":
            reply = builder.high_sale()
        elif intent == "balanced_sale":
            reply = builder.balanced_sale()
        elif intent == "future_price":
            reply = builder.future_price()
        elif intent == "listing_copy":
            reply = builder.listing_copy()
        elif intent == "similar_listings":
            reply = builder.similar_listings()
        elif intent == "calculation_explain":
            reply = builder.calculation_explain()
        elif intent == "report":
            reply = builder.report()
        elif intent == "missing_fields":
            reply = builder.missing_fields()
        elif intent == "negotiation":
            reply = builder.negotiation()
        elif intent == "risk":
            reply = builder.risk()
        elif intent == "sales_plan":
            reply = builder.sales_plan()
        elif intent == "buyer_perspective":
            reply = builder.buyer_perspective()
        elif intent == "market_commentary":
            reply = builder.market_commentary()
        elif intent == "price_scenario":
            requested_price = SellerScenarioParser.parse_price(message)
            reply = builder.price_scenario(requested_price)
        elif intent == "help":
            reply = builder.help()
        else:
            reply = builder.general()

        return {
            "success": True,
            "reply": reply,
            "intent": intent,
            "strategy": {
                "estimated_price": round(strategy.estimated_price),
                "estimated_price_text": format_price(strategy.estimated_price),
                "quick_sale_price": round(strategy.quick_sale_price),
                "quick_sale_price_text": format_price(strategy.quick_sale_price),
                "balanced_sale_price": round(strategy.balanced_sale_price),
                "balanced_sale_price_text": format_price(strategy.balanced_sale_price),
                "high_sale_price": round(strategy.high_sale_price),
                "high_sale_price_text": format_price(strategy.high_sale_price),
                "six_month_prediction": round(strategy.six_month_prediction),
                "six_month_prediction_text": format_price(strategy.six_month_prediction),
                "confidence": strategy.confidence,
                "match_level": strategy.match_level,
                "similar_count": strategy.similar_count,
            },
            "comparable_summary": {
                "count": comparable.get("count", 0),
                "match_level": comparable.get("match_level"),
                "confidence": comparable.get("confidence"),
                "average_price_text": format_price(comparable.get("average_price", 0)),
                "median_price_text": format_price(comparable.get("median_price", 0)),
                "average_m2_price_text": format_price(comparable.get("average_m2_price", 0)),
                "examples": comparable.get("examples", []),
            },
        }


# =========================================================
# 6) DISA ACILAN FONKSIYONLAR
# =========================================================

map_agent = HouseAIMapAgent()
seller_agent = HouseAISellerAgent()


def map_chatbot_reply(payload: Dict[str, Any]) -> Dict[str, Any]:
    return map_agent.chat(payload)


def seller_chatbot_reply(payload: Dict[str, Any]) -> Dict[str, Any]:
    return seller_agent.chat(payload)