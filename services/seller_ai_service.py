"""
HouseAI Seller AI Service
Bu dosya 3. sayfadaki chatbot zekasını Python tarafına taşır.
seller.js artık cevap üretmez; sadece /api/seller-chatbot endpoint'ine mesaj gönderir.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
LISTINGS_PATH = BASE_DIR / "listings.json"


# =========================================================
# GENEL YARDIMCI FONKSİYONLAR
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
    return normalize_text(text).replace(" mahallesi", "").strip()


def load_json_file(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def average(values: List[float]) -> float:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if not clean:
        return 0
    return float(sum(clean) / len(clean))


def median(values: List[float]) -> float:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if not clean:
        return 0
    return float(statistics.median(clean))


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
# DATA CLASSES
# =========================================================

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
        return f"{self.ilce} / {self.mahalle}".strip(" /")


@dataclass
class PriceStrategy:
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


# =========================================================
# INTENT DETECTOR
# =========================================================

class IntentDetector:
    @staticmethod
    def detect(message: str) -> str:
        text = normalize_text(message)

        rules = [
            ("quick_sale", ["hizli", "hızlı", "acil", "cabuk", "çabuk", "hemen sat", "beklemek istemiyorum"]),
            ("high_sale", ["yuksek", "yüksek", "pahali", "pahalı", "pazarlik", "pazarlık", "ustten", "üstten"]),
            ("balanced_sale", ["normal", "dengeli", "makul", "ortalama fiyattan"]),
            ("future_price", ["6 ay", "alti ay", "altı ay", "gelecek", "sonra", "ileride"]),
            ("listing_copy", ["ilan aciklama", "ilan açıklama", "aciklama yaz", "açıklama yaz", "baslik", "başlık", "ilan metni"]),
            ("similar_listings", ["benzer", "emsal", "karsilastir", "karşılaştır", "ilanlara bak", "ilanlari goster", "ilanları göster"]),
            ("calculation_explain", ["nasil hesap", "nasıl hesap", "neden", "formul", "formül", "mantik", "mantık"]),
            ("report", ["rapor", "ozet", "özet", "detayli analiz", "detaylı analiz"]),
            ("missing_fields", ["eksik", "hangi bilgi", "tamamlamam", "ne lazim", "ne lazım"]),
            ("negotiation", ["teklif", "pazarlik payi", "pazarlık payı", "kapanis", "kapanış", "son fiyat"]),
            ("risk", ["risk", "satilmazsa", "satılmazsa", "beklerse", "alici cikmazsa", "alıcı çıkmazsa"]),
            ("marketing", ["nasil satarim", "nasıl satarım", "one cikar", "öne çıkar", "fotograf", "fotoğraf", "pazarlama"]),
            ("market", ["piyasa", "istanbul", "haber", "konut", "emlak piyasasi", "emlak piyasası"]),
            ("help", ["yardim", "yardım", "ne yapabilirsin", "komut", "neler yap"]),
        ]

        for intent, keywords in rules:
            for keyword in keywords:
                if normalize_text(keyword) in text:
                    return intent

        return "general"


# =========================================================
# COMPARABLE LISTING ANALYZER
# =========================================================

class ComparableListingAnalyzer:
    def __init__(self, listings_path: Path = LISTINGS_PATH):
        self.listings_path = listings_path
        self.listings = load_json_file(listings_path)

    def find_similar(self, prop: PropertyInput) -> Dict[str, Any]:
        valid = [item for item in self.listings if self._is_valid(item)]

        stages = [
            (
                "Aynı mahalle + aynı oda tipi + benzer m²",
                "Orta-Yüksek",
                lambda item: self._same_district(item, prop)
                and self._same_neighborhood(item, prop)
                and self._same_room(item, prop)
                and self._similar_m2(item, prop),
                3,
            ),
            (
                "Aynı mahalle + aynı oda tipi",
                "Orta-Yüksek",
                lambda item: self._same_district(item, prop)
                and self._same_neighborhood(item, prop)
                and self._same_room(item, prop),
                2,
            ),
            (
                "Aynı mahalle tüm oda tipleri",
                "Orta",
                lambda item: self._same_district(item, prop)
                and self._same_neighborhood(item, prop),
                2,
            ),
            (
                "Aynı ilçe + aynı oda tipi",
                "Düşük-Orta",
                lambda item: self._same_district(item, prop)
                and self._same_room(item, prop),
                2,
            ),
            (
                "Aynı ilçe genel veri",
                "Düşük",
                lambda item: self._same_district(item, prop),
                1,
            ),
        ]

        for match_level, confidence, predicate, min_count in stages:
            items = [item for item in valid if predicate(item)]
            if len(items) >= min_count:
                if match_level == "Aynı mahalle + aynı oda tipi + benzer m²" and len(items) >= 6:
                    confidence = "Yüksek"
                return self._result(items, match_level, confidence)

        return self._result(valid[:20], "Genel veri", "Çok Düşük")

    def _is_valid(self, item: Dict[str, Any]) -> bool:
        return get_listing_price(item) > 0 and get_listing_net_m2(item) > 0

    def _same_district(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        return normalize_text(item.get("district")) == normalize_text(prop.ilce)

    def _same_neighborhood(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        return normalize_neighborhood(item.get("neighborhood")) == normalize_neighborhood(prop.mahalle)

    def _same_room(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        return get_listing_room(item) == prop.oda and get_listing_salon(item) == prop.salon

    def _similar_m2(self, item: Dict[str, Any], prop: PropertyInput) -> bool:
        if prop.net_metrekare <= 0:
            return True
        item_m2 = get_listing_net_m2(item)
        return prop.net_metrekare * 0.75 <= item_m2 <= prop.net_metrekare * 1.25

    def _result(self, items: List[Dict[str, Any]], match_level: str, confidence: str) -> Dict[str, Any]:
        sorted_items = sorted(items, key=lambda item: get_listing_price(item))
        prices = [get_listing_price(item) for item in sorted_items if get_listing_price(item) > 0]
        m2_prices = [get_listing_m2_price(item) for item in sorted_items if get_listing_m2_price(item) > 0]

        return {
            "items": sorted_items,
            "match_level": match_level,
            "confidence": confidence,
            "count": len(sorted_items),
            "average_price": average(prices),
            "median_price": median(prices),
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "average_m2_price": average(m2_prices),
            "median_m2_price": median(m2_prices),
            "examples": self._examples(sorted_items[:10]),
        }

    def _examples(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        examples = []

        for item in items:
            price = get_listing_price(item)
            net = get_listing_net_m2(item)
            m2_price = price / net if net else 0

            examples.append({
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

        return examples


# =========================================================
# PRICE STRATEGY ENGINE
# =========================================================

class SellerStrategyEngine:
    def build_strategy(self, prop: PropertyInput, prediction_result: Dict[str, Any], comparable_result: Dict[str, Any]) -> PriceStrategy:
        estimated = self._get_estimated_price(prop, prediction_result, comparable_result)
        quick = estimated * 0.96
        balanced = estimated * 1.02
        high = estimated * 1.08
        six_month = estimated * self._future_multiplier(comparable_result)

        return PriceStrategy(
            estimated_price=estimated,
            quick_sale_price=quick,
            balanced_sale_price=balanced,
            high_sale_price=high,
            six_month_prediction=six_month,
            confidence=comparable_result.get("confidence", "Orta"),
            match_level=comparable_result.get("match_level", "Bilinmiyor"),
            similar_count=comparable_result.get("count", 0),
            average_price=comparable_result.get("average_price", 0),
            median_price=comparable_result.get("median_price", 0),
            average_m2_price=comparable_result.get("average_m2_price", 0),
            median_m2_price=comparable_result.get("median_m2_price", 0),
            min_price=comparable_result.get("min_price", 0),
            max_price=comparable_result.get("max_price", 0),
        )

    def _get_estimated_price(self, prop: PropertyInput, prediction_result: Dict[str, Any], comparable_result: Dict[str, Any]) -> float:
        if prediction_result and prediction_result.get("success") and prediction_result.get("prediction"):
            value = safe_number(prediction_result["prediction"].get("estimated_price"), None)
            if value and value > 0:
                return value

        base_m2 = comparable_result.get("median_m2_price") or comparable_result.get("average_m2_price") or 0
        estimated = base_m2 * prop.net_metrekare

        if estimated <= 0:
            estimated = comparable_result.get("median_price") or comparable_result.get("average_price") or 0

        return self._apply_adjustments(estimated, prop)

    def _apply_adjustments(self, price: float, prop: PropertyInput) -> float:
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

    def _future_multiplier(self, comparable_result: Dict[str, Any]) -> float:
        confidence = comparable_result.get("confidence", "")
        if confidence == "Yüksek":
            return 1.04
        if confidence == "Orta-Yüksek":
            return 1.035
        if confidence == "Orta":
            return 1.03
        return 1.02


# =========================================================
# RESPONSE BUILDER
# =========================================================

class SellerResponseBuilder:
    def __init__(self, prop: PropertyInput, strategy: PriceStrategy, comparable_result: Dict[str, Any], prediction_result: Dict[str, Any]):
        self.prop = prop
        self.strategy = strategy
        self.comparable_result = comparable_result
        self.prediction_result = prediction_result or {}

    def quick_sale(self) -> str:
        return (
            f"Hızlı satış için önerim: <strong>{format_price(self.strategy.quick_sale_price)}</strong><br><br>"
            f"Bu fiyat, tahmini piyasa değerinin biraz altında konumlanır. Amaç daha fazla talep almak "
            f"ve ilanın bekleme süresini azaltmaktır.<br><br>"
            f"İlk 7-14 gün içinde talep gelmezse fotoğraf, başlık ve açıklama da revize edilmelidir."
        )

    def high_sale(self) -> str:
        return (
            f"Yüksekten deneme fiyatı: <strong>{format_price(self.strategy.high_sale_price)}</strong><br><br>"
            f"Bu fiyat pazarlık payı bırakır. Ancak satış süresi uzayabilir. "
            f"2-4 hafta içinde talep düşükse fiyatı <strong>{format_price(self.strategy.balanced_sale_price)}</strong> seviyesine çekmek mantıklı olur."
        )

    def balanced_sale(self) -> str:
        return (
            f"Dengeli satış fiyatı: <strong>{format_price(self.strategy.balanced_sale_price)}</strong><br><br>"
            f"Bu fiyat piyasa değerine yakın ama satıcı için küçük pazarlık alanı bırakan daha güvenli bir seviyedir."
        )

    def future_price(self) -> str:
        return (
            f"6 ay sonrası basit tahmin: <strong>{format_price(self.strategy.six_month_prediction)}</strong><br><br>"
            f"Bu tahmin mevcut benzer ilan verisi ve kısa dönem varsayımsal fiyat artışıyla hesaplandı. "
            f"Canlı haber/RSS/piyasa endeksi bağlandığında daha hassas hale getirilebilir."
        )

    def similar_listings(self) -> str:
        examples = self.comparable_result.get("examples", [])
        if not examples:
            return "Benzer ilan bulunamadı. Bu yüzden karşılaştırma güveni düşük."

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
        model_type = self.prediction_result.get("model_type", "basic/fallback estimator")
        return (
            f"Hesaplama mantığı:<br><br>"
            f"1. 2. sayfadaki ev bilgileri okundu.<br>"
            f"2. {self.prop.location_text()} bölgesinde benzer ilanlar arandı.<br>"
            f"3. Aynı mahalle, aynı oda tipi ve benzer metrekare önceliklendirildi.<br>"
            f"4. Model sonucu varsa kullanıldı, yoksa ortalama/medyan m² fiyatı üzerinden tahmin yapıldı.<br>"
            f"5. Site, krediye uygunluk, tapu, ısıtma, banyo ve kat bilgisi küçük düzeltmeler olarak uygulandı.<br><br>"
            f"Kullanılan model tipi: <strong>{model_type}</strong><br>"
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
            f"Dengeli ilan fiyatı: <strong>{format_price(self.strategy.balanced_sale_price)}</strong><br>"
            f"Yüksekten deneme fiyatı: <strong>{format_price(self.strategy.high_sale_price)}</strong><br>"
            f"6 ay sonrası tahmin: <strong>{format_price(self.strategy.six_month_prediction)}</strong><br><br>"
            f"Benzer ilan sayısı: <strong>{self.strategy.similar_count}</strong><br>"
            f"Karşılaştırma seviyesi: <strong>{self.strategy.match_level}</strong><br>"
            f"Tahmin güveni: <strong>{self.strategy.confidence}</strong>"
        )

    def listing_copy(self) -> str:
        title1 = f"{self.prop.mahalle} Bölgesinde {self.prop.room_text()} Satılık Daire"
        title2 = f"{self.prop.ilce}'de {int(self.prop.net_metrekare)} m² Net Kullanımlı Satılık Daire"
        title3 = f"{self.prop.mahalle}'nde Merkezi Konumda Satılık {self.prop.room_text()} Daire"

        description = (
            f"{self.prop.ilce} {self.prop.mahalle} bölgesinde yer alan bu {self.prop.room_text()} daire, "
            f"{int(self.prop.net_metrekare)} m² net ve {int(self.prop.brut_metrekare)} m² brüt kullanım alanı sunmaktadır. "
            f"{self.prop.binanin_yasi} yaş aralığındaki binada bulunan daire, "
            f"{self.prop.isitma_tipi or 'belirtilen ısıtma tipi'} ile ısınmaktadır. "
            f"Bölgedeki benzer ilanlar ve HouseAI Seller analizine göre dengeli ilan fiyatı "
            f"yaklaşık {format_price(self.strategy.balanced_sale_price)} seviyesindedir."
        )

        return (
            f"<strong>Başlık önerileri:</strong><br>"
            f"1. {title1}<br>"
            f"2. {title2}<br>"
            f"3. {title3}<br><br>"
            f"<strong>İlan açıklaması:</strong><br>{description}"
        )

    def missing_fields(self) -> str:
        checks = [
            ("İlçe", self.prop.ilce),
            ("Mahalle", self.prop.mahalle),
            ("Net m²", self.prop.net_metrekare),
            ("Brüt m²", self.prop.brut_metrekare),
            ("Oda", self.prop.oda),
            ("Salon", self.prop.salon),
            ("Bina yaşı", self.prop.binanin_yasi),
            ("Binanın kat sayısı", self.prop.binanin_kat_sayisi),
            ("Bulunduğu kat", self.prop.bulundugu_kat_numeric),
            ("Isıtma tipi", self.prop.isitma_tipi),
            ("Tapu durumu", self.prop.tapu_durumu),
            ("Banyo sayısı", self.prop.banyo_sayisi),
        ]

        missing = [label for label, value in checks if value is None or value == "" or value == 0]

        if not missing:
            return "Temel alanların çoğu dolu görünüyor. Tahmin için yeterli veri var."

        return "Şu bilgiler eksik veya zayıf görünüyor:<br><br>" + "<br>".join([f"• {item}" for item in missing])

    def negotiation(self) -> str:
        expected_low = self.strategy.estimated_price * 0.99
        expected_high = self.strategy.estimated_price * 1.03
        return (
            f"Pazarlık stratejisi:<br><br>"
            f"İlanı <strong>{format_price(self.strategy.high_sale_price)}</strong> civarında açarsan pazarlık payı bırakmış olursun.<br><br>"
            f"Makul kapanış aralığı: <strong>{format_price(expected_low)} - {format_price(expected_high)}</strong><br><br>"
            f"Alıcı ciddi ise önce evin konumu, m² avantajı, tapu/kredi durumu ve benzer ilan fiyatları vurgulanmalı."
        )

    def risk(self) -> str:
        return (
            f"Satış riski:<br><br>"
            f"• Hızlı satış fiyatı düşük risklidir.<br>"
            f"• Dengeli fiyat orta risklidir.<br>"
            f"• Yüksekten deneme fiyatı daha risklidir; satış süresi uzayabilir.<br><br>"
            f"Eğer {format_price(self.strategy.high_sale_price)} seviyesinden çıkılır ve 2-4 hafta içinde talep gelmezse, "
            f"fiyatı {format_price(self.strategy.balanced_sale_price)} seviyesine çekmek mantıklı olur."
        )

    def marketing(self) -> str:
        return (
            f"İlanı daha hızlı satmak için öneriler:<br><br>"
            f"1. İlk fotoğraf aydınlık salon veya en güçlü oda olmalı.<br>"
            f"2. Başlıkta mahalle + net m² + oda tipi mutlaka geçmeli.<br>"
            f"3. Açıklamada ulaşım, market, okul ve sağlık noktalarına yakınlık vurgulanmalı.<br>"
            f"4. İlk 2 hafta ilan performansı takip edilmeli.<br>"
            f"5. Görüntülenme düşükse fiyat veya başlık revize edilmeli."
        )

    def market_commentary(self) -> str:
        return (
            f"Bu sürümde canlı haber/RSS bağlantısı henüz aktif değil. "
            f"Ama mevcut listings.json verisi üzerinden bölgesel piyasa yorumu yapılabiliyor.<br><br>"
            f"{self.prop.location_text()} için benzer ilan sayısı: <strong>{self.strategy.similar_count}</strong><br>"
            f"Ortalama fiyat: <strong>{format_price(self.strategy.average_price)}</strong><br>"
            f"Ortalama m² fiyatı: <strong>{format_price(self.strategy.average_m2_price)}</strong><br><br>"
            f"Bu bölgedeki veriye göre dengeli satış fiyatı <strong>{format_price(self.strategy.balanced_sale_price)}</strong> bandında konumlanabilir."
        )

    def help(self) -> str:
        return (
            f"Ben HouseAI Seller olarak şunları yapabilirim:<br><br>"
            f"• Hızlı satış fiyatı öneririm<br>"
            f"• Dengeli ve yüksekten deneme fiyatı üretirim<br>"
            f"• Benzer ilanları analiz ederim<br>"
            f"• İlan başlığı ve açıklaması yazarım<br>"
            f"• Pazarlık stratejisi çıkarırım<br>"
            f"• 6 ay sonrası tahmini yorumlarım<br>"
            f"• Satış raporu oluştururum<br><br>"
            f"Örnek: <strong>Hızlı satmak istiyorum</strong> veya <strong>Rapor oluştur</strong>"
        )

    def general(self) -> str:
        return (
            f"Şu anki ana önerim:<br><br>"
            f"• Tahmini piyasa değeri: <strong>{format_price(self.strategy.estimated_price)}</strong><br>"
            f"• Hızlı satış: <strong>{format_price(self.strategy.quick_sale_price)}</strong><br>"
            f"• Dengeli satış: <strong>{format_price(self.strategy.balanced_sale_price)}</strong><br>"
            f"• Yüksekten deneme: <strong>{format_price(self.strategy.high_sale_price)}</strong><br>"
            f"• 6 ay sonrası tahmin: <strong>{format_price(self.strategy.six_month_prediction)}</strong><br><br>"
            f"Daha detaylı yönlendirme için “hızlı satmak istiyorum”, “yüksekten koymak istiyorum”, "
            f"“ilan açıklaması yaz” veya “rapor oluştur” yazabilirsin."
        )


# =========================================================
# MAIN SERVICE
# =========================================================

class HouseAISellerService:
    def __init__(self):
        self.comparable_analyzer = ComparableListingAnalyzer()
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
        strategy = self.strategy_engine.build_strategy(prop, prediction_result, comparable)

        intent = IntentDetector.detect(message)
        builder = SellerResponseBuilder(prop, strategy, comparable, prediction_result)

        reply_map = {
            "quick_sale": builder.quick_sale,
            "high_sale": builder.high_sale,
            "balanced_sale": builder.balanced_sale,
            "future_price": builder.future_price,
            "listing_copy": builder.listing_copy,
            "similar_listings": builder.similar_listings,
            "calculation_explain": builder.calculation_explain,
            "report": builder.report,
            "missing_fields": builder.missing_fields,
            "negotiation": builder.negotiation,
            "risk": builder.risk,
            "marketing": builder.marketing,
            "market": builder.market_commentary,
            "help": builder.help,
            "general": builder.general,
        }

        reply_function = reply_map.get(intent, builder.general)

        return {
            "success": True,
            "reply": reply_function(),
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


houseai_seller_service = HouseAISellerService()


def seller_chatbot_reply(payload: Dict[str, Any]) -> Dict[str, Any]:
    return houseai_seller_service.chat(payload)
