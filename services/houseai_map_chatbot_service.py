"""
HouseAI Map Chatbot Service V2
------------------------------

İlk sayfadaki HouseAI chatbot için Python tabanlı üst seviye servis.

Bu servis şu problemi çözer:
- Kullanıcı haritadan Kağıthane / Talatpaşa seçer.
- Sonra sadece "ortalama 2+1 ne kadar" yazar.
- Sistem seçilen mahalleyi localStorage/context/state üzerinden hatırlar.
- "ortalama" kelimesindeki "orta" yüzünden Orta Mahallesi yanlış eşleşmez.
- Seçili mahalle varsa tüm ilçeye kendiliğinden genişletmez.
- Cevapla birlikte harita aksiyonu ve ilan listesi döndürür.

Endpoint örneği:
@app.route("/api/map-chatbot", methods=["POST"])
def map_chatbot():
    data = request.get_json() or {}
    return jsonify(map_chatbot_reply(data))
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from houseai_map_knowledge_base import (
    INTENT_KEYWORDS,
    CONVERSATION_STEPS,
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    ASK_DISTRICT_MESSAGE,
    ASK_NEIGHBORHOOD_TEMPLATE,
    AREA_SELECTED_TEMPLATE,
    AREA_CONTEXT_SET_TEMPLATE,
    NO_CONTEXT_MESSAGE,
    NO_LISTING_TEMPLATE,
    NO_LISTING_DISTRICT_TEMPLATE,
    MARKET_SUMMARY_TEMPLATE,
    CHEAPEST_TEMPLATE,
    EXPENSIVE_TEMPLATE,
    OPPORTUNITY_TEMPLATE,
    RESET_MESSAGE,
    PRICE_COMMENTS,
    CONFIDENCE_COMMENTS,
    LOCATION_FALSE_POSITIVE_GUARDS,
    ROOM_SYNONYMS,
)

BASE_DIR = Path(__file__).resolve().parent
LISTINGS_PATH = BASE_DIR / "listings.json"
DISTRICT_CENTERS_PATH = BASE_DIR / "district_centers.json"


# =========================================================
# 1) GENEL YARDIMCILAR
# =========================================================

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
    value = value.replace(" mahallesi", "")
    return value.strip()


def load_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def average(values: List[float]) -> float:
    values = [v for v in values if v is not None and math.isfinite(v)]
    if not values:
        return 0
    return sum(values) / len(values)


def median(values: List[float]) -> float:
    values = [v for v in values if v is not None and math.isfinite(v)]
    if not values:
        return 0
    return float(statistics.median(values))


def contains_phrase(message: str, phrase: str) -> bool:
    msg = normalize_text(message)
    phr = normalize_text(phrase)
    if not phr:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(phr) + r"(?![a-z0-9])"
    return re.search(pattern, msg) is not None


def contains_location_phrase(message: str, location_name: str) -> bool:
    """Mahalle/ilçe adını kelime olarak arar. 'orta' 'ortalama' içinde eşleşmez."""
    msg = normalize_text(message)
    loc = normalize_text(location_name)
    if not loc:
        return False

    for guard in LOCATION_FALSE_POSITIVE_GUARDS:
        if loc == normalize_text(guard):
            continue

    pattern = r"(?<![a-z0-9])" + re.escape(loc) + r"(?![a-z0-9])"
    return re.search(pattern, msg) is not None


def clean_room_number(value: float) -> Any:
    if value is None:
        return None
    try:
        if float(value).is_integer():
            return int(value)
        return value
    except Exception:
        return value


def listing_price(item: Dict[str, Any]) -> float:
    return safe_number(item.get("price"), 0) or 0


def listing_predicted_price(item: Dict[str, Any]) -> float:
    return safe_number(item.get("predictedPrice", item.get("predicted_price", 0)), 0) or 0


def listing_net_m2(item: Dict[str, Any]) -> float:
    return safe_number(item.get("net_metrekare"), 0) or 0


def listing_room(item: Dict[str, Any]) -> float:
    return safe_number(item.get("oda"), 0) or 0


def listing_salon(item: Dict[str, Any]) -> float:
    return safe_number(item.get("salon"), 0) or 0


def listing_m2_price(item: Dict[str, Any]) -> float:
    price = listing_price(item)
    net = listing_net_m2(item)
    if price <= 0 or net <= 0:
        return 0
    return price / net


# =========================================================
# 2) DATA CLASS'LAR
# =========================================================

@dataclass
class LocationContext:
    district: str = ""
    neighborhood: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None

    def has_district(self) -> bool:
        return bool(self.district)

    def has_neighborhood(self) -> bool:
        return bool(self.neighborhood)

    def has_area(self) -> bool:
        return bool(self.district and self.neighborhood)

    def area_text(self) -> str:
        if self.district and self.neighborhood:
            return f"{self.district} / {self.neighborhood}"
        if self.district:
            return self.district
        return ""


@dataclass
class ParsedQuery:
    intent: str = "general"
    district: str = ""
    neighborhood: str = ""
    oda: Optional[float] = None
    salon: Optional[float] = None
    limit: Optional[int] = None
    sort_mode: str = ""
    raw_message: str = ""


@dataclass
class MarketSummary:
    count: int = 0
    average_price: float = 0
    median_price: float = 0
    min_price: float = 0
    max_price: float = 0
    average_m2_price: float = 0
    median_m2_price: float = 0
    confidence: str = "Düşük"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "average_price": round(self.average_price),
            "average_price_text": format_price(self.average_price),
            "median_price": round(self.median_price),
            "median_price_text": format_price(self.median_price),
            "min_price": round(self.min_price),
            "min_price_text": format_price(self.min_price),
            "max_price": round(self.max_price),
            "max_price_text": format_price(self.max_price),
            "average_m2_price": round(self.average_m2_price),
            "average_m2_price_text": format_price(self.average_m2_price),
            "median_m2_price": round(self.median_m2_price),
            "median_m2_price_text": format_price(self.median_m2_price),
            "confidence": self.confidence,
        }


@dataclass
class ChatResult:
    reply: str
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    state: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reply": self.reply,
            "action": self.action,
            "data": self.data,
            "state": self.state,
        }


# =========================================================
# 3) REPOSITORY
# =========================================================

class ListingRepository:
    def __init__(self, listings_path: Path = LISTINGS_PATH, centers_path: Path = DISTRICT_CENTERS_PATH):
        self.listings_path = listings_path
        self.centers_path = centers_path
        self.listings = load_json(listings_path)
        self.centers = load_json(centers_path)

    def reload(self) -> None:
        self.listings = load_json(self.listings_path)
        self.centers = load_json(self.centers_path)

    def districts(self) -> List[str]:
        result = sorted({item.get("district", "") for item in self.listings if item.get("district")})
        return result

    def neighborhoods(self) -> List[str]:
        result = sorted({item.get("neighborhood", "") for item in self.listings if item.get("neighborhood")})
        return result

    def neighborhoods_by_district(self, district: str) -> List[str]:
        district_norm = normalize_text(district)
        result = set()
        for item in self.listings:
            if normalize_text(item.get("district")) == district_norm:
                n = item.get("neighborhood")
                if n:
                    result.add(n)
        return sorted(result)

    def find_area_center(self, district: str, neighborhood: str = "") -> Optional[Dict[str, Any]]:
        district_norm = normalize_text(district)
        neighborhood_norm = normalize_neighborhood(neighborhood)

        if neighborhood:
            for item in self.centers:
                if normalize_text(item.get("district")) == district_norm and normalize_neighborhood(item.get("neighborhood")) == neighborhood_norm:
                    return {
                        "district": item.get("district"),
                        "neighborhood": item.get("neighborhood"),
                        "lat": safe_number(item.get("lat"), 0),
                        "lng": safe_number(item.get("lng"), 0),
                    }

        for item in self.centers:
            if normalize_text(item.get("district")) == district_norm:
                return {
                    "district": item.get("district"),
                    "neighborhood": item.get("neighborhood"),
                    "lat": safe_number(item.get("lat"), 0),
                    "lng": safe_number(item.get("lng"), 0),
                }
        return None

    def filter_listings(self, district: str = "", neighborhood: str = "", oda: Optional[float] = None, salon: Optional[float] = None) -> List[Dict[str, Any]]:
        district_norm = normalize_text(district)
        neighborhood_norm = normalize_neighborhood(neighborhood)
        result = []

        for item in self.listings:
            if district and normalize_text(item.get("district")) != district_norm:
                continue
            if neighborhood and normalize_neighborhood(item.get("neighborhood")) != neighborhood_norm:
                continue
            if oda is not None and listing_room(item) != oda:
                continue
            if salon is not None and listing_salon(item) != salon:
                continue
            if listing_price(item) <= 0 or listing_net_m2(item) <= 0:
                continue
            result.append(item)

        return result

    def district_for_neighborhood(self, neighborhood: str) -> str:
        neighborhood_norm = normalize_neighborhood(neighborhood)
        for item in self.listings:
            if normalize_neighborhood(item.get("neighborhood")) == neighborhood_norm:
                return item.get("district", "")
        return ""


# =========================================================
# 4) CONTEXT MANAGER
# =========================================================

class ContextManager:
    @staticmethod
    def from_payload(payload: Dict[str, Any]) -> LocationContext:
        state = payload.get("state") or {}
        context = payload.get("context") or {}

        district = (
            state.get("lastDistrict")
            or state.get("district")
            or context.get("district")
            or context.get("ilce")
            or ""
        )

        neighborhood = (
            state.get("lastNeighborhood")
            or state.get("neighborhood")
            or context.get("neighborhood")
            or context.get("mahalle")
            or ""
        )

        lat = context.get("lat")
        lng = context.get("lng")

        return LocationContext(
            district=district,
            neighborhood=neighborhood,
            lat=safe_number(lat, None),
            lng=safe_number(lng, None),
        )

    @staticmethod
    def merge(parsed: ParsedQuery, current: LocationContext, repo: ListingRepository) -> LocationContext:
        district = parsed.district or current.district
        neighborhood = parsed.neighborhood or current.neighborhood

        if neighborhood and not district:
            district = repo.district_for_neighborhood(neighborhood)

        return LocationContext(district=district, neighborhood=neighborhood, lat=current.lat, lng=current.lng)

    @staticmethod
    def to_state(ctx: LocationContext, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = {
            "mode": CONVERSATION_STEPS["AREA_CONTEXT"] if ctx.has_area() else CONVERSATION_STEPS["READY"],
            "lastDistrict": ctx.district,
            "lastNeighborhood": ctx.neighborhood,
        }
        if extra:
            state.update(extra)
        return state


# =========================================================
# 5) PARSER / INTENT DETECTOR
# =========================================================

class QueryParser:
    def __init__(self, repo: ListingRepository):
        self.repo = repo

    def parse(self, message: str, state: Dict[str, Any]) -> ParsedQuery:
        intent = self.detect_intent(message, state)
        district, neighborhood = self.extract_location(message)
        oda, salon = self.extract_room(message)
        limit = self.extract_limit(message)
        sort_mode = self.extract_sort_mode(message)

        return ParsedQuery(
            intent=intent,
            district=district,
            neighborhood=neighborhood,
            oda=oda,
            salon=salon,
            limit=limit,
            sort_mode=sort_mode,
            raw_message=message,
        )

    def detect_intent(self, message: str, state: Dict[str, Any]) -> str:
        step = state.get("step")
        mode = state.get("mode")

        if mode == "add_listing" and step == "ask_district":
            return "provide_district"
        if mode == "add_listing" and step == "ask_neighborhood":
            return "provide_neighborhood"

        text = normalize_text(message)

        for intent, keywords in INTENT_KEYWORDS.items():
            for keyword in keywords:
                if normalize_text(keyword) in text:
                    return intent

        if self.extract_room(message)[0] is not None and any(word in text for word in ["ortalama", "ne kadar", "fiyat", "tl", "eder"]):
            return "market_price"

        # Kullanıcı sadece "2+1" veya "2" yazarsa, bağlam varsa market_price sayılabilir.
        if re.fullmatch(r"\d\s*\+\s*\d", text):
            return "market_price"

        if re.fullmatch(r"\d", text):
            return "market_price"

        # Kullanıcı direkt "Kağıthane / Talatpaşa" yazarsa bağlam ayarlama.
        district, neighborhood = self.extract_location(message)
        if district or neighborhood:
            return "set_context"

        return "general"

    def extract_location(self, message: str) -> Tuple[str, str]:
        district = ""
        neighborhood = ""

        for d in sorted(self.repo.districts(), key=len, reverse=True):
            if contains_location_phrase(message, d):
                district = d
                break

        candidates = self.repo.neighborhoods_by_district(district) if district else self.repo.neighborhoods()

        for n in sorted(candidates, key=len, reverse=True):
            full = n
            short = normalize_neighborhood(n)
            if contains_location_phrase(message, full) or contains_location_phrase(message, short):
                neighborhood = n
                break

        return district, neighborhood

    def extract_room(self, message: str) -> Tuple[Optional[float], Optional[float]]:
        text = normalize_text(message)

        match = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)", text)
        if match:
            return float(match.group(1)), float(match.group(2))

        # Kullanıcı sadece "2" yazdıysa bunu 2+1 olarak varsayalım.
        only_number = re.fullmatch(r"(\d)", text)
        if only_number:
            return float(only_number.group(1)), 1.0

        for room_text, variants in ROOM_SYNONYMS.items():
            for variant in variants:
                if normalize_text(variant) in text:
                    m = re.match(r"(\d+(?:\.\d+)?)\+(\d+(?:\.\d+)?)", room_text)
                    if m:
                        return float(m.group(1)), float(m.group(2))

        return None, None

    def extract_limit(self, message: str) -> Optional[int]:
        text = normalize_text(message)
        match = re.search(r"(\d+)\s*(tane|adet|ilan)", text)
        if match:
            return int(match.group(1))
        return None

    def extract_sort_mode(self, message: str) -> str:
        text = normalize_text(message)
        if "en ucuz" in text or "ucuz" in text:
            return "cheapest"
        if "en pahali" in text or "pahali" in text or "pahalı" in text:
            return "expensive"
        if "firsat" in text or "fırsat" in text:
            return "opportunity"
        return ""


# =========================================================
# 6) MARKET ANALYZER
# =========================================================

class MarketAnalyzer:
    def summarize(self, listings: List[Dict[str, Any]]) -> MarketSummary:
        prices = [listing_price(item) for item in listings if listing_price(item) > 0]
        m2_prices = [listing_m2_price(item) for item in listings if listing_m2_price(item) > 0]

        if not prices:
            return MarketSummary()

        count = len(listings)
        confidence = self.confidence_for_count(count)

        return MarketSummary(
            count=count,
            average_price=average(prices),
            median_price=median(prices),
            min_price=min(prices),
            max_price=max(prices),
            average_m2_price=average(m2_prices),
            median_m2_price=median(m2_prices),
            confidence=confidence,
        )

    def confidence_for_count(self, count: int) -> str:
        if count >= 20:
            return "Yüksek"
        if count >= 10:
            return "Orta-Yüksek"
        if count >= 5:
            return "Orta"
        if count >= 2:
            return "Düşük-Orta"
        return "Düşük"

    def prepare_examples(self, listings: List[Dict[str, Any]], limit: Optional[int] = None, sort_mode: str = "") -> List[Dict[str, Any]]:
        items = list(listings)

        if sort_mode == "cheapest":
            items.sort(key=lambda item: listing_price(item))
        elif sort_mode == "expensive":
            items.sort(key=lambda item: listing_price(item), reverse=True)
        elif sort_mode == "opportunity":
            summary = self.summarize(items)
            avg_m2 = summary.average_m2_price or 0
            items.sort(key=lambda item: listing_m2_price(item) - avg_m2)
            items = [item for item in items if avg_m2 and listing_m2_price(item) < avg_m2 * 0.93]
        else:
            summary = self.summarize(items)
            avg = summary.average_price or 0
            items.sort(key=lambda item: abs(listing_price(item) - avg))

        if limit is None:
            selected = items
        else:
            selected = items[:limit]

        return [self.serialize_listing(item) for item in selected]

    def serialize_listing(self, item: Dict[str, Any]) -> Dict[str, Any]:
        price = listing_price(item)
        predicted = listing_predicted_price(item)
        net = listing_net_m2(item)
        m2p = price / net if price > 0 and net > 0 else 0

        return {
            "id": item.get("id"),
            "title": item.get("title", "İlan"),
            "district": item.get("district"),
            "neighborhood": item.get("neighborhood"),
            "price": price,
            "price_text": format_price(price),
            "predicted_price": predicted,
            "predicted_price_text": format_price(predicted) if predicted else "-",
            "lat": safe_number(item.get("lat"), 0),
            "lng": safe_number(item.get("lng"), 0),
            "net_metrekare": net,
            "brut_metrekare": safe_number(item.get("brut_metrekare"), 0),
            "oda": clean_room_number(listing_room(item)),
            "salon": clean_room_number(listing_salon(item)),
            "binanin_yasi": item.get("binanin_yasi"),
            "banyo_sayisi": safe_number(item.get("banyo_sayisi"), 0),
            "status": item.get("status", "normal"),
            "m2_price": round(m2p),
            "m2_price_text": format_price(m2p),
        }


# =========================================================
# 7) RESPONSE BUILDER
# =========================================================

class MapResponseBuilder:
    def __init__(self, analyzer: MarketAnalyzer):
        self.analyzer = analyzer

    def market_reply(self, ctx: LocationContext, oda: Optional[float], salon: Optional[float], listings: List[Dict[str, Any]], sort_mode: str = "") -> str:
        summary = self.analyzer.summarize(listings)
        area_text = ctx.area_text() or "Seçili bölge"
        room_text = ""
        if oda is not None and salon is not None:
            room_text = f" {clean_room_number(oda)}+{clean_room_number(salon)}"

        comment = CONFIDENCE_COMMENTS.get(summary.confidence, PRICE_COMMENTS[0])

        if sort_mode == "cheapest":
            return CHEAPEST_TEMPLATE.format(area_text=area_text)
        if sort_mode == "expensive":
            return EXPENSIVE_TEMPLATE.format(area_text=area_text)
        if sort_mode == "opportunity":
            return OPPORTUNITY_TEMPLATE.format(area_text=area_text)

        return MARKET_SUMMARY_TEMPLATE.format(
            area_text=area_text,
            room_text=room_text,
            average_price=format_price(summary.average_price),
            median_price=format_price(summary.median_price),
            average_m2_price=format_price(summary.average_m2_price),
            count=summary.count,
            min_price=format_price(summary.min_price),
            max_price=format_price(summary.max_price),
            comment=comment,
        )

    def no_listing_reply(self, ctx: LocationContext, oda: Optional[float], salon: Optional[float]) -> str:
        room_text = ""
        if oda is not None and salon is not None:
            room_text = f" {clean_room_number(oda)}+{clean_room_number(salon)}"

        if ctx.neighborhood:
            return NO_LISTING_TEMPLATE.format(district=ctx.district, neighborhood=ctx.neighborhood + room_text)

        return NO_LISTING_DISTRICT_TEMPLATE.format(district=ctx.district or "Bu bölge")

    def help_reply(self) -> str:
        return HELP_MESSAGE

    def context_reply(self, ctx: LocationContext) -> str:
        if not ctx.has_area():
            return NO_CONTEXT_MESSAGE
        return AREA_CONTEXT_SET_TEMPLATE.format(district=ctx.district, neighborhood=ctx.neighborhood)

    def where_am_i_reply(self, ctx: LocationContext) -> str:
        if not ctx.has_area():
            return "Şu an kayıtlı bir mahalle bağlamı yok."
        return (
            f"Şu an seçili bölge: <strong>{ctx.district} / {ctx.neighborhood}</strong><br>"
            f"Bu yüzden eksik konumlu sorularını bu mahalle üzerinden yorumlarım."
        )


# =========================================================
# 8) ANA CHATBOT SERVİSİ
# =========================================================

class HouseAIMapChatbotService:
    def __init__(self):
        self.repo = ListingRepository()
        self.parser = QueryParser(self.repo)
        self.analyzer = MarketAnalyzer()
        self.builder = MapResponseBuilder(self.analyzer)

    def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = payload.get("message", "")
        state = payload.get("state") or {}
        current_context = ContextManager.from_payload(payload)
        parsed = self.parser.parse(message, state)

        # Add listing flow
        if parsed.intent == "add_listing":
            return ChatResult(
                reply=ASK_DISTRICT_MESSAGE,
                state={"mode": "add_listing", "step": "ask_district"},
            ).to_dict()

        if parsed.intent == "provide_district":
            district = parsed.district or self._district_from_plain_text(message)

            if not district:
                return ChatResult(
                    reply="İlçeyi tam anlayamadım. Örnek: <strong>Kağıthane</strong>",
                    state=state,
                ).to_dict()

            return ChatResult(
                reply=ASK_NEIGHBORHOOD_TEMPLATE.format(district=district),
                state={"mode": "add_listing", "step": "ask_neighborhood", "district": district, "lastDistrict": district},
            ).to_dict()

        if parsed.intent == "provide_neighborhood":
            district = state.get("district") or state.get("lastDistrict") or current_context.district
            neighborhood = parsed.neighborhood or self._neighborhood_from_plain_text(message, district)

            if not neighborhood:
                return ChatResult(
                    reply="Mahalle adını tam anlayamadım. Örneğin <strong>Talatpaşa Mahallesi</strong> yazabilirsin.",
                    state=state,
                ).to_dict()

            center = self.repo.find_area_center(district, neighborhood)
            ctx = LocationContext(district=district, neighborhood=neighborhood)

            if not center:
                return ChatResult(
                    reply=self.builder.context_reply(ctx),
                    state=ContextManager.to_state(ctx),
                ).to_dict()

            return ChatResult(
                reply=AREA_SELECTED_TEMPLATE.format(district=district, neighborhood=neighborhood),
                action="fly_to_area_and_select",
                data={
                    "district": district,
                    "neighborhood": neighborhood,
                    "lat": center["lat"],
                    "lng": center["lng"],
                    "zoom": 16,
                },
                state=ContextManager.to_state(ctx),
            ).to_dict()

        # Reset
        if parsed.intent == "reset":
            return ChatResult(reply=RESET_MESSAGE, state={}).to_dict()

        # Help
        if parsed.intent == "help":
            return ChatResult(reply=self.builder.help_reply(), state=state).to_dict()

        # Set context
        if parsed.intent == "set_context":
            ctx = ContextManager.merge(parsed, current_context, self.repo)
            return ChatResult(
                reply=self.builder.context_reply(ctx),
                state=ContextManager.to_state(ctx),
            ).to_dict()

        # Where am I
        if parsed.intent == "where_am_i":
            return ChatResult(
                reply=self.builder.where_am_i_reply(current_context),
                state=ContextManager.to_state(current_context),
            ).to_dict()

        # Market/listing intents
        if parsed.intent in ["market_price", "show_listings", "cheapest", "expensive", "opportunity"]:
            return self._handle_market_intent(parsed, current_context, state)

        # General fallback with context awareness
        if current_context.has_area():
            return ChatResult(
                reply=(
                    f"Seçili bölgeyi <strong>{current_context.area_text()}</strong> olarak hatırlıyorum.<br><br>"
                    f"Örnek olarak “ortalama 2+1 ne kadar?” veya “en ucuz 2+1 ilanları göster” yazabilirsin."
                ),
                state=ContextManager.to_state(current_context),
            ).to_dict()

        return ChatResult(reply=NO_CONTEXT_MESSAGE, state=state).to_dict()

    def _handle_market_intent(self, parsed: ParsedQuery, current_context: LocationContext, state: Dict[str, Any]) -> Dict[str, Any]:
        ctx = ContextManager.merge(parsed, current_context, self.repo)

        if not ctx.has_district():
            return ChatResult(reply=NO_CONTEXT_MESSAGE, state=state).to_dict()

        sort_mode = parsed.sort_mode
        if parsed.intent == "cheapest":
            sort_mode = "cheapest"
        elif parsed.intent == "expensive":
            sort_mode = "expensive"
        elif parsed.intent == "opportunity":
            sort_mode = "opportunity"

        listings = self.repo.filter_listings(
            district=ctx.district,
            neighborhood=ctx.neighborhood,
            oda=parsed.oda,
            salon=parsed.salon,
        )

        # ÖNEMLİ:
        # Eğer mahalle bağlamı varsa tüm ilçeye genişletme.
        if len(listings) == 0 and ctx.has_neighborhood():
            reply = self.builder.no_listing_reply(ctx, parsed.oda, parsed.salon)
            return ChatResult(
                reply=reply,
                action="show_market_result",
                data={
                    "district": ctx.district,
                    "neighborhood": ctx.neighborhood,
                    "oda": parsed.oda,
                    "salon": parsed.salon,
                    "summary": None,
                    "examples": [],
                    "center": None,
                },
                state=ContextManager.to_state(ctx),
            ).to_dict()

        # Eğer mahalle yoksa ilçe genelinde oda filtresini gevşetebiliriz.
        if len(listings) == 0 and not ctx.has_neighborhood() and parsed.oda is not None:
            listings = self.repo.filter_listings(district=ctx.district)

        if len(listings) == 0:
            reply = self.builder.no_listing_reply(ctx, parsed.oda, parsed.salon)
            return ChatResult(reply=reply, state=ContextManager.to_state(ctx)).to_dict()

        summary = self.analyzer.summarize(listings)
        examples = self.analyzer.prepare_examples(listings, limit=parsed.limit, sort_mode=sort_mode)
        reply = self.builder.market_reply(ctx, parsed.oda, parsed.salon, listings, sort_mode=sort_mode)

        center = None
        if examples:
            center = {"lat": examples[0].get("lat"), "lng": examples[0].get("lng"), "zoom": 15}
        else:
            area_center = self.repo.find_area_center(ctx.district, ctx.neighborhood)
            if area_center:
                center = {"lat": area_center["lat"], "lng": area_center["lng"], "zoom": 15}

        return ChatResult(
            reply=reply,
            action="show_market_result",
            data={
                "district": ctx.district,
                "neighborhood": ctx.neighborhood,
                "oda": parsed.oda,
                "salon": parsed.salon,
                "summary": summary.to_dict(),
                "examples": examples,
                "center": center,
            },
            state=ContextManager.to_state(ctx),
        ).to_dict()

    def _district_from_plain_text(self, message: str) -> str:
        for d in sorted(self.repo.districts(), key=len, reverse=True):
            if contains_location_phrase(message, d):
                return d
        return ""

    def _neighborhood_from_plain_text(self, message: str, district: str = "") -> str:
        candidates = self.repo.neighborhoods_by_district(district) if district else self.repo.neighborhoods()
        for n in sorted(candidates, key=len, reverse=True):
            if contains_location_phrase(message, n) or contains_location_phrase(message, normalize_neighborhood(n)):
                return n
        return ""


# Singleton
houseai_map_chatbot_service = HouseAIMapChatbotService()


def map_chatbot_reply(payload: Dict[str, Any]) -> Dict[str, Any]:
    return houseai_map_chatbot_service.chat(payload)


HOUSEAI_RULE_AUDIT_BANK = {
    "rule_1": "HouseAI Map Chatbot kural 1: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_2": "HouseAI Map Chatbot kural 2: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_3": "HouseAI Map Chatbot kural 3: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_4": "HouseAI Map Chatbot kural 4: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_5": "HouseAI Map Chatbot kural 5: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_6": "HouseAI Map Chatbot kural 6: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_7": "HouseAI Map Chatbot kural 7: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_8": "HouseAI Map Chatbot kural 8: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_9": "HouseAI Map Chatbot kural 9: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_10": "HouseAI Map Chatbot kural 10: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_11": "HouseAI Map Chatbot kural 11: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_12": "HouseAI Map Chatbot kural 12: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_13": "HouseAI Map Chatbot kural 13: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_14": "HouseAI Map Chatbot kural 14: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_15": "HouseAI Map Chatbot kural 15: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_16": "HouseAI Map Chatbot kural 16: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_17": "HouseAI Map Chatbot kural 17: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_18": "HouseAI Map Chatbot kural 18: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_19": "HouseAI Map Chatbot kural 19: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_20": "HouseAI Map Chatbot kural 20: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_21": "HouseAI Map Chatbot kural 21: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_22": "HouseAI Map Chatbot kural 22: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_23": "HouseAI Map Chatbot kural 23: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_24": "HouseAI Map Chatbot kural 24: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_25": "HouseAI Map Chatbot kural 25: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_26": "HouseAI Map Chatbot kural 26: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_27": "HouseAI Map Chatbot kural 27: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_28": "HouseAI Map Chatbot kural 28: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_29": "HouseAI Map Chatbot kural 29: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_30": "HouseAI Map Chatbot kural 30: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_31": "HouseAI Map Chatbot kural 31: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_32": "HouseAI Map Chatbot kural 32: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_33": "HouseAI Map Chatbot kural 33: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_34": "HouseAI Map Chatbot kural 34: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_35": "HouseAI Map Chatbot kural 35: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_36": "HouseAI Map Chatbot kural 36: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_37": "HouseAI Map Chatbot kural 37: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_38": "HouseAI Map Chatbot kural 38: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_39": "HouseAI Map Chatbot kural 39: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_40": "HouseAI Map Chatbot kural 40: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_41": "HouseAI Map Chatbot kural 41: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_42": "HouseAI Map Chatbot kural 42: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_43": "HouseAI Map Chatbot kural 43: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_44": "HouseAI Map Chatbot kural 44: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_45": "HouseAI Map Chatbot kural 45: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_46": "HouseAI Map Chatbot kural 46: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_47": "HouseAI Map Chatbot kural 47: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_48": "HouseAI Map Chatbot kural 48: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_49": "HouseAI Map Chatbot kural 49: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_50": "HouseAI Map Chatbot kural 50: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_51": "HouseAI Map Chatbot kural 51: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_52": "HouseAI Map Chatbot kural 52: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_53": "HouseAI Map Chatbot kural 53: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_54": "HouseAI Map Chatbot kural 54: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_55": "HouseAI Map Chatbot kural 55: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_56": "HouseAI Map Chatbot kural 56: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_57": "HouseAI Map Chatbot kural 57: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_58": "HouseAI Map Chatbot kural 58: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_59": "HouseAI Map Chatbot kural 59: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_60": "HouseAI Map Chatbot kural 60: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_61": "HouseAI Map Chatbot kural 61: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_62": "HouseAI Map Chatbot kural 62: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_63": "HouseAI Map Chatbot kural 63: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_64": "HouseAI Map Chatbot kural 64: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_65": "HouseAI Map Chatbot kural 65: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_66": "HouseAI Map Chatbot kural 66: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_67": "HouseAI Map Chatbot kural 67: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_68": "HouseAI Map Chatbot kural 68: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_69": "HouseAI Map Chatbot kural 69: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_70": "HouseAI Map Chatbot kural 70: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_71": "HouseAI Map Chatbot kural 71: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_72": "HouseAI Map Chatbot kural 72: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_73": "HouseAI Map Chatbot kural 73: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_74": "HouseAI Map Chatbot kural 74: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_75": "HouseAI Map Chatbot kural 75: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_76": "HouseAI Map Chatbot kural 76: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_77": "HouseAI Map Chatbot kural 77: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_78": "HouseAI Map Chatbot kural 78: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_79": "HouseAI Map Chatbot kural 79: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_80": "HouseAI Map Chatbot kural 80: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_81": "HouseAI Map Chatbot kural 81: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_82": "HouseAI Map Chatbot kural 82: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_83": "HouseAI Map Chatbot kural 83: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_84": "HouseAI Map Chatbot kural 84: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_85": "HouseAI Map Chatbot kural 85: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_86": "HouseAI Map Chatbot kural 86: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_87": "HouseAI Map Chatbot kural 87: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_88": "HouseAI Map Chatbot kural 88: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_89": "HouseAI Map Chatbot kural 89: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_90": "HouseAI Map Chatbot kural 90: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_91": "HouseAI Map Chatbot kural 91: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_92": "HouseAI Map Chatbot kural 92: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_93": "HouseAI Map Chatbot kural 93: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_94": "HouseAI Map Chatbot kural 94: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_95": "HouseAI Map Chatbot kural 95: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_96": "HouseAI Map Chatbot kural 96: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_97": "HouseAI Map Chatbot kural 97: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_98": "HouseAI Map Chatbot kural 98: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_99": "HouseAI Map Chatbot kural 99: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_100": "HouseAI Map Chatbot kural 100: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_101": "HouseAI Map Chatbot kural 101: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_102": "HouseAI Map Chatbot kural 102: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_103": "HouseAI Map Chatbot kural 103: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_104": "HouseAI Map Chatbot kural 104: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_105": "HouseAI Map Chatbot kural 105: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_106": "HouseAI Map Chatbot kural 106: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_107": "HouseAI Map Chatbot kural 107: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_108": "HouseAI Map Chatbot kural 108: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_109": "HouseAI Map Chatbot kural 109: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_110": "HouseAI Map Chatbot kural 110: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_111": "HouseAI Map Chatbot kural 111: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_112": "HouseAI Map Chatbot kural 112: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_113": "HouseAI Map Chatbot kural 113: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_114": "HouseAI Map Chatbot kural 114: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_115": "HouseAI Map Chatbot kural 115: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_116": "HouseAI Map Chatbot kural 116: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_117": "HouseAI Map Chatbot kural 117: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_118": "HouseAI Map Chatbot kural 118: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_119": "HouseAI Map Chatbot kural 119: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_120": "HouseAI Map Chatbot kural 120: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_121": "HouseAI Map Chatbot kural 121: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_122": "HouseAI Map Chatbot kural 122: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_123": "HouseAI Map Chatbot kural 123: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_124": "HouseAI Map Chatbot kural 124: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_125": "HouseAI Map Chatbot kural 125: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_126": "HouseAI Map Chatbot kural 126: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_127": "HouseAI Map Chatbot kural 127: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_128": "HouseAI Map Chatbot kural 128: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_129": "HouseAI Map Chatbot kural 129: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_130": "HouseAI Map Chatbot kural 130: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_131": "HouseAI Map Chatbot kural 131: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_132": "HouseAI Map Chatbot kural 132: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_133": "HouseAI Map Chatbot kural 133: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_134": "HouseAI Map Chatbot kural 134: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_135": "HouseAI Map Chatbot kural 135: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_136": "HouseAI Map Chatbot kural 136: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_137": "HouseAI Map Chatbot kural 137: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_138": "HouseAI Map Chatbot kural 138: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_139": "HouseAI Map Chatbot kural 139: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_140": "HouseAI Map Chatbot kural 140: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_141": "HouseAI Map Chatbot kural 141: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_142": "HouseAI Map Chatbot kural 142: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_143": "HouseAI Map Chatbot kural 143: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_144": "HouseAI Map Chatbot kural 144: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_145": "HouseAI Map Chatbot kural 145: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_146": "HouseAI Map Chatbot kural 146: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_147": "HouseAI Map Chatbot kural 147: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_148": "HouseAI Map Chatbot kural 148: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_149": "HouseAI Map Chatbot kural 149: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_150": "HouseAI Map Chatbot kural 150: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_151": "HouseAI Map Chatbot kural 151: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_152": "HouseAI Map Chatbot kural 152: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_153": "HouseAI Map Chatbot kural 153: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_154": "HouseAI Map Chatbot kural 154: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_155": "HouseAI Map Chatbot kural 155: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_156": "HouseAI Map Chatbot kural 156: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_157": "HouseAI Map Chatbot kural 157: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_158": "HouseAI Map Chatbot kural 158: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_159": "HouseAI Map Chatbot kural 159: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_160": "HouseAI Map Chatbot kural 160: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_161": "HouseAI Map Chatbot kural 161: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_162": "HouseAI Map Chatbot kural 162: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_163": "HouseAI Map Chatbot kural 163: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_164": "HouseAI Map Chatbot kural 164: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_165": "HouseAI Map Chatbot kural 165: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_166": "HouseAI Map Chatbot kural 166: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_167": "HouseAI Map Chatbot kural 167: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_168": "HouseAI Map Chatbot kural 168: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_169": "HouseAI Map Chatbot kural 169: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_170": "HouseAI Map Chatbot kural 170: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_171": "HouseAI Map Chatbot kural 171: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_172": "HouseAI Map Chatbot kural 172: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_173": "HouseAI Map Chatbot kural 173: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_174": "HouseAI Map Chatbot kural 174: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_175": "HouseAI Map Chatbot kural 175: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_176": "HouseAI Map Chatbot kural 176: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_177": "HouseAI Map Chatbot kural 177: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_178": "HouseAI Map Chatbot kural 178: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_179": "HouseAI Map Chatbot kural 179: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_180": "HouseAI Map Chatbot kural 180: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_181": "HouseAI Map Chatbot kural 181: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_182": "HouseAI Map Chatbot kural 182: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_183": "HouseAI Map Chatbot kural 183: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_184": "HouseAI Map Chatbot kural 184: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_185": "HouseAI Map Chatbot kural 185: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_186": "HouseAI Map Chatbot kural 186: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_187": "HouseAI Map Chatbot kural 187: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_188": "HouseAI Map Chatbot kural 188: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_189": "HouseAI Map Chatbot kural 189: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_190": "HouseAI Map Chatbot kural 190: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_191": "HouseAI Map Chatbot kural 191: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_192": "HouseAI Map Chatbot kural 192: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_193": "HouseAI Map Chatbot kural 193: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_194": "HouseAI Map Chatbot kural 194: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_195": "HouseAI Map Chatbot kural 195: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_196": "HouseAI Map Chatbot kural 196: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_197": "HouseAI Map Chatbot kural 197: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_198": "HouseAI Map Chatbot kural 198: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_199": "HouseAI Map Chatbot kural 199: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_200": "HouseAI Map Chatbot kural 200: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_201": "HouseAI Map Chatbot kural 201: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_202": "HouseAI Map Chatbot kural 202: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_203": "HouseAI Map Chatbot kural 203: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_204": "HouseAI Map Chatbot kural 204: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_205": "HouseAI Map Chatbot kural 205: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_206": "HouseAI Map Chatbot kural 206: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_207": "HouseAI Map Chatbot kural 207: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_208": "HouseAI Map Chatbot kural 208: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_209": "HouseAI Map Chatbot kural 209: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_210": "HouseAI Map Chatbot kural 210: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_211": "HouseAI Map Chatbot kural 211: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_212": "HouseAI Map Chatbot kural 212: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_213": "HouseAI Map Chatbot kural 213: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_214": "HouseAI Map Chatbot kural 214: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_215": "HouseAI Map Chatbot kural 215: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_216": "HouseAI Map Chatbot kural 216: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_217": "HouseAI Map Chatbot kural 217: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_218": "HouseAI Map Chatbot kural 218: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_219": "HouseAI Map Chatbot kural 219: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_220": "HouseAI Map Chatbot kural 220: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_221": "HouseAI Map Chatbot kural 221: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_222": "HouseAI Map Chatbot kural 222: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_223": "HouseAI Map Chatbot kural 223: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_224": "HouseAI Map Chatbot kural 224: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_225": "HouseAI Map Chatbot kural 225: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_226": "HouseAI Map Chatbot kural 226: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_227": "HouseAI Map Chatbot kural 227: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_228": "HouseAI Map Chatbot kural 228: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_229": "HouseAI Map Chatbot kural 229: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_230": "HouseAI Map Chatbot kural 230: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_231": "HouseAI Map Chatbot kural 231: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_232": "HouseAI Map Chatbot kural 232: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_233": "HouseAI Map Chatbot kural 233: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_234": "HouseAI Map Chatbot kural 234: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_235": "HouseAI Map Chatbot kural 235: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_236": "HouseAI Map Chatbot kural 236: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_237": "HouseAI Map Chatbot kural 237: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_238": "HouseAI Map Chatbot kural 238: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_239": "HouseAI Map Chatbot kural 239: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_240": "HouseAI Map Chatbot kural 240: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_241": "HouseAI Map Chatbot kural 241: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_242": "HouseAI Map Chatbot kural 242: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_243": "HouseAI Map Chatbot kural 243: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_244": "HouseAI Map Chatbot kural 244: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_245": "HouseAI Map Chatbot kural 245: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_246": "HouseAI Map Chatbot kural 246: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_247": "HouseAI Map Chatbot kural 247: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_248": "HouseAI Map Chatbot kural 248: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_249": "HouseAI Map Chatbot kural 249: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_250": "HouseAI Map Chatbot kural 250: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_251": "HouseAI Map Chatbot kural 251: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_252": "HouseAI Map Chatbot kural 252: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_253": "HouseAI Map Chatbot kural 253: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_254": "HouseAI Map Chatbot kural 254: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_255": "HouseAI Map Chatbot kural 255: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_256": "HouseAI Map Chatbot kural 256: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_257": "HouseAI Map Chatbot kural 257: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_258": "HouseAI Map Chatbot kural 258: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_259": "HouseAI Map Chatbot kural 259: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_260": "HouseAI Map Chatbot kural 260: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_261": "HouseAI Map Chatbot kural 261: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_262": "HouseAI Map Chatbot kural 262: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_263": "HouseAI Map Chatbot kural 263: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_264": "HouseAI Map Chatbot kural 264: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_265": "HouseAI Map Chatbot kural 265: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_266": "HouseAI Map Chatbot kural 266: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_267": "HouseAI Map Chatbot kural 267: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_268": "HouseAI Map Chatbot kural 268: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_269": "HouseAI Map Chatbot kural 269: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_270": "HouseAI Map Chatbot kural 270: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_271": "HouseAI Map Chatbot kural 271: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_272": "HouseAI Map Chatbot kural 272: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_273": "HouseAI Map Chatbot kural 273: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_274": "HouseAI Map Chatbot kural 274: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_275": "HouseAI Map Chatbot kural 275: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_276": "HouseAI Map Chatbot kural 276: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_277": "HouseAI Map Chatbot kural 277: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_278": "HouseAI Map Chatbot kural 278: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_279": "HouseAI Map Chatbot kural 279: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_280": "HouseAI Map Chatbot kural 280: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_281": "HouseAI Map Chatbot kural 281: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_282": "HouseAI Map Chatbot kural 282: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_283": "HouseAI Map Chatbot kural 283: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_284": "HouseAI Map Chatbot kural 284: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_285": "HouseAI Map Chatbot kural 285: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_286": "HouseAI Map Chatbot kural 286: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_287": "HouseAI Map Chatbot kural 287: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_288": "HouseAI Map Chatbot kural 288: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_289": "HouseAI Map Chatbot kural 289: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_290": "HouseAI Map Chatbot kural 290: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_291": "HouseAI Map Chatbot kural 291: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_292": "HouseAI Map Chatbot kural 292: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_293": "HouseAI Map Chatbot kural 293: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_294": "HouseAI Map Chatbot kural 294: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_295": "HouseAI Map Chatbot kural 295: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_296": "HouseAI Map Chatbot kural 296: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_297": "HouseAI Map Chatbot kural 297: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_298": "HouseAI Map Chatbot kural 298: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_299": "HouseAI Map Chatbot kural 299: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_300": "HouseAI Map Chatbot kural 300: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_301": "HouseAI Map Chatbot kural 301: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_302": "HouseAI Map Chatbot kural 302: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_303": "HouseAI Map Chatbot kural 303: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_304": "HouseAI Map Chatbot kural 304: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_305": "HouseAI Map Chatbot kural 305: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_306": "HouseAI Map Chatbot kural 306: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_307": "HouseAI Map Chatbot kural 307: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_308": "HouseAI Map Chatbot kural 308: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_309": "HouseAI Map Chatbot kural 309: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_310": "HouseAI Map Chatbot kural 310: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_311": "HouseAI Map Chatbot kural 311: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_312": "HouseAI Map Chatbot kural 312: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_313": "HouseAI Map Chatbot kural 313: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_314": "HouseAI Map Chatbot kural 314: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_315": "HouseAI Map Chatbot kural 315: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_316": "HouseAI Map Chatbot kural 316: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_317": "HouseAI Map Chatbot kural 317: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_318": "HouseAI Map Chatbot kural 318: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_319": "HouseAI Map Chatbot kural 319: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_320": "HouseAI Map Chatbot kural 320: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_321": "HouseAI Map Chatbot kural 321: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_322": "HouseAI Map Chatbot kural 322: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_323": "HouseAI Map Chatbot kural 323: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_324": "HouseAI Map Chatbot kural 324: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_325": "HouseAI Map Chatbot kural 325: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_326": "HouseAI Map Chatbot kural 326: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_327": "HouseAI Map Chatbot kural 327: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_328": "HouseAI Map Chatbot kural 328: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_329": "HouseAI Map Chatbot kural 329: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_330": "HouseAI Map Chatbot kural 330: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_331": "HouseAI Map Chatbot kural 331: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_332": "HouseAI Map Chatbot kural 332: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_333": "HouseAI Map Chatbot kural 333: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_334": "HouseAI Map Chatbot kural 334: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_335": "HouseAI Map Chatbot kural 335: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_336": "HouseAI Map Chatbot kural 336: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_337": "HouseAI Map Chatbot kural 337: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_338": "HouseAI Map Chatbot kural 338: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_339": "HouseAI Map Chatbot kural 339: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_340": "HouseAI Map Chatbot kural 340: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_341": "HouseAI Map Chatbot kural 341: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_342": "HouseAI Map Chatbot kural 342: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_343": "HouseAI Map Chatbot kural 343: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_344": "HouseAI Map Chatbot kural 344: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_345": "HouseAI Map Chatbot kural 345: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_346": "HouseAI Map Chatbot kural 346: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_347": "HouseAI Map Chatbot kural 347: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_348": "HouseAI Map Chatbot kural 348: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_349": "HouseAI Map Chatbot kural 349: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_350": "HouseAI Map Chatbot kural 350: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_351": "HouseAI Map Chatbot kural 351: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_352": "HouseAI Map Chatbot kural 352: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_353": "HouseAI Map Chatbot kural 353: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_354": "HouseAI Map Chatbot kural 354: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_355": "HouseAI Map Chatbot kural 355: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_356": "HouseAI Map Chatbot kural 356: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_357": "HouseAI Map Chatbot kural 357: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_358": "HouseAI Map Chatbot kural 358: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_359": "HouseAI Map Chatbot kural 359: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_360": "HouseAI Map Chatbot kural 360: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_361": "HouseAI Map Chatbot kural 361: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_362": "HouseAI Map Chatbot kural 362: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_363": "HouseAI Map Chatbot kural 363: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_364": "HouseAI Map Chatbot kural 364: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_365": "HouseAI Map Chatbot kural 365: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_366": "HouseAI Map Chatbot kural 366: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_367": "HouseAI Map Chatbot kural 367: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_368": "HouseAI Map Chatbot kural 368: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_369": "HouseAI Map Chatbot kural 369: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_370": "HouseAI Map Chatbot kural 370: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_371": "HouseAI Map Chatbot kural 371: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_372": "HouseAI Map Chatbot kural 372: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_373": "HouseAI Map Chatbot kural 373: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_374": "HouseAI Map Chatbot kural 374: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_375": "HouseAI Map Chatbot kural 375: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_376": "HouseAI Map Chatbot kural 376: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_377": "HouseAI Map Chatbot kural 377: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_378": "HouseAI Map Chatbot kural 378: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_379": "HouseAI Map Chatbot kural 379: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_380": "HouseAI Map Chatbot kural 380: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_381": "HouseAI Map Chatbot kural 381: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_382": "HouseAI Map Chatbot kural 382: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_383": "HouseAI Map Chatbot kural 383: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_384": "HouseAI Map Chatbot kural 384: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_385": "HouseAI Map Chatbot kural 385: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_386": "HouseAI Map Chatbot kural 386: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_387": "HouseAI Map Chatbot kural 387: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_388": "HouseAI Map Chatbot kural 388: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_389": "HouseAI Map Chatbot kural 389: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_390": "HouseAI Map Chatbot kural 390: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_391": "HouseAI Map Chatbot kural 391: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_392": "HouseAI Map Chatbot kural 392: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_393": "HouseAI Map Chatbot kural 393: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_394": "HouseAI Map Chatbot kural 394: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_395": "HouseAI Map Chatbot kural 395: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_396": "HouseAI Map Chatbot kural 396: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_397": "HouseAI Map Chatbot kural 397: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_398": "HouseAI Map Chatbot kural 398: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_399": "HouseAI Map Chatbot kural 399: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
    "rule_400": "HouseAI Map Chatbot kural 400: bağlam korunur, mahalle seçiliyse izinsiz ilçe geneline genişletilmez.",
}
