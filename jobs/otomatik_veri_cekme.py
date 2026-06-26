from __future__ import annotations

import json
import re
import time
import shutil
import statistics
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from urllib.parse import urljoin


from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# =========================================================
# AYARLAR
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

LISTINGS_PATH = BASE_DIR / "data" / "listings.json"
IMPORTS_DIR = BASE_DIR / "imports"
BACKUP_DIR = BASE_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"

LIST_PAGE_URL = (
    "https://www.emlakjet.com/satilik-daire/istanbul"
    "?filtreler=max-fiyat=20000000&min-fiyat=1000000&tarih-araligi=son-24-saat"
)

# İlan limiti yok. Kaç link bulursa işler.
# Bu sadece sonsuz döngü engeli. 50 sayfa genelde fazlasıyla yeterli.
MAX_PAGES_SAFETY = 50

# Art arda 2 sayfada yeni link bulunmazsa pagination bitti sayılır.
STOP_AFTER_EMPTY_PAGE_COUNT = 2

# Siteyi yormamak için her ilan arasında bekleme.
REQUEST_DELAY_SECONDS = 1.5

# İşlem sonunda rapor açılsın mı?
OPEN_REPORT_AFTER_RUN = True

LINKS_OUTPUT_PATH = IMPORTS_DIR / "emlakjet_last_24h_links.json"
PENDING_OUTPUT_PATH = IMPORTS_DIR / "emlakjet_pending.json"
REJECTED_OUTPUT_PATH = IMPORTS_DIR / "emlakjet_rejected.json"
SKIPPED_OUTPUT_PATH = IMPORTS_DIR / "emlakjet_skipped.json"
ADDED_OUTPUT_PATH = IMPORTS_DIR / "emlakjet_added_apply.json"
LAST_RUN_OUTPUT_PATH = IMPORTS_DIR / "daily_pipeline_last_run.json"
REPORT_PATH = IMPORTS_DIR / "imported_listings_report.html"


# =========================================================
# GENEL YARDIMCI FONKSİYONLAR
# =========================================================

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def backup_file(path: Path, label: str = "backup") -> Optional[Path]:
    if not path.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{path.stem}_{label}_{timestamp}{path.suffix}"

    shutil.copy2(path, backup_path)

    return backup_path


def normalize_text(value: Any) -> str:
    text = str(value or "").lower().strip()

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

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_number(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default

    text = str(value)
    text = text.replace("₺", "")
    text = text.replace("TL", "")
    text = text.replace("m²", "")
    text = text.replace("m2", "")
    text = text.replace(".", "")
    text = text.replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text)

    if not text:
        return default

    try:
        return float(text)
    except Exception:
        return default


def safe_meter(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default

    text = str(value).strip()
    text = text.replace("metre", "m")
    text = text.replace("M", "m")

    thousand_match = re.search(r"(\d{1,3})\.(\d{3})\s*m", text)
    if thousand_match:
        return int(thousand_match.group(1) + thousand_match.group(2))

    decimal_match = re.search(r"(\d+)[.,](\d+)", text)
    if decimal_match:
        number = float(decimal_match.group(1) + "." + decimal_match.group(2))
        return int(round(number))

    int_match = re.search(r"\d+", text)
    if int_match:
        return int(int_match.group(0))

    return default


def to_int_or_none(value: Any) -> Optional[int]:
    number = safe_number(value, None)

    if number is None:
        return None

    return int(round(number))


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    title = title.replace(" | Emlakjet", "").strip()
    return title


def format_price(value: Any) -> str:
    try:
        number = int(round(float(value or 0)))
        return f"{number:,}".replace(",", ".") + " TL"
    except Exception:
        return "0 TL"


def html_escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


# =========================================================
# LİNK ÇEKME + PAGINATION
# =========================================================

def extract_listing_id(url: str) -> Optional[str]:
    match = re.search(r"-(\d+)(?:$|\?)", url)

    if match:
        return match.group(1)

    match = re.search(r"/listing/(\d+)", url)

    if match:
        return match.group(1)

    return None


def is_listing_url(url: str) -> bool:
    if not url:
        return False

    if "/ilan/" not in url:
        return False

    if not extract_listing_id(url):
        return False

    return True


def normalize_listing_url(href: str) -> str:
    full_url = urljoin("https://www.emlakjet.com", href)
    full_url = full_url.split("?")[0]
    full_url = full_url.rstrip("/")
    return full_url


def normalize_page_url(href: str) -> str:
    full_url = urljoin("https://www.emlakjet.com", href)
    full_url = full_url.rstrip("/")
    return full_url


def build_paginated_url(page_no: int) -> str:
    if page_no <= 1:
        return LIST_PAGE_URL

    if "?" in LIST_PAGE_URL:
        base, query = LIST_PAGE_URL.split("?", 1)
        return f"{base.rstrip('/')}/{page_no}?{query}"

    return f"{LIST_PAGE_URL.rstrip('/')}/{page_no}"


def collect_links_from_page(page) -> List[Dict[str, str]]:
    hrefs = page.eval_on_selector_all(
        "a[href]",
        """
        elements => elements.map(a => a.getAttribute("href"))
        """
    )

    results = []
    seen = set()

    for href in hrefs:
        if not href:
            continue

        url = normalize_listing_url(href)

        if not is_listing_url(url):
            continue

        listing_id = extract_listing_id(url)

        if not listing_id:
            continue

        if listing_id in seen:
            continue

        seen.add(listing_id)

        results.append({
            "listing_id": listing_id,
            "url": url,
        })

    return results


def find_next_page_url(page, current_page_no: int) -> Optional[str]:
    """
    Emlakjet pagination yapısı değişebildiği için iki yöntem kullanıyoruz:
    1. Sonraki/İleri/Next gibi yazan linkleri yakala.
    2. Sayfa numarası current+1 olan linkleri yakala.
    """

    anchors = page.eval_on_selector_all(
        "a[href]",
        """
        elements => elements.map(a => ({
            href: a.getAttribute("href"),
            text: (a.innerText || a.textContent || "").trim()
        }))
        """
    )

    next_page_no = current_page_no + 1
    candidates = []

    for anchor in anchors:
        href = anchor.get("href")
        text = anchor.get("text", "")

        if not href:
            continue

        full_url = normalize_page_url(href)

        if "/ilan/" in full_url:
            continue

        if "emlakjet.com" not in full_url:
            continue

        if "/satilik-daire/istanbul" not in full_url:
            continue

        text_norm = normalize_text(text)

        if (
            "sonraki" in text_norm
            or "ileri" in text_norm
            or "next" in text_norm
            or text_norm == str(next_page_no)
        ):
            candidates.append(full_url)
            continue

        if f"/{next_page_no}?" in full_url or f"/{next_page_no}/" in full_url:
            candidates.append(full_url)
            continue

        if f"sayfa={next_page_no}" in full_url or f"page={next_page_no}" in full_url:
            candidates.append(full_url)
            continue

    if candidates:
        return candidates[0]

    return None


def auto_scroll(page, scroll_count: int = 8, wait_seconds: float = 0.8) -> None:
    for _ in range(scroll_count):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(wait_seconds)


def scrape_listing_links() -> List[Dict[str, str]]:
    """
    Son 24 saat filtreli liste sayfasından tüm pagination sayfalarını gezerek ilan linklerini toplar.
    İlan limiti yoktur.
    """

    all_links = []
    seen_listing_ids = set()
    visited_page_urls = set()
    empty_page_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1600},
        )

        page = context.new_page()

        page.set_default_timeout(20000)
        page.set_default_navigation_timeout(30000)

        current_page_url = LIST_PAGE_URL

        for page_no in range(1, MAX_PAGES_SAFETY + 1):
            if current_page_url in visited_page_urls:
                print("Pagination durdu: aynı sayfa tekrar geldi.")
                break

            visited_page_urls.add(current_page_url)

            print("\nListe sayfası açılıyor:")
            print(f"Sayfa {page_no}: {current_page_url}")

            try:
                page.goto(current_page_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as error:
                print(f"Liste sayfası açılamadı: {error}")
                break

            time.sleep(2)

            print("Sayfa aşağı kaydırılıyor...")
            auto_scroll(page)

            page_links = collect_links_from_page(page)

            new_count = 0

            for item in page_links:
                listing_id = item["listing_id"]

                if listing_id in seen_listing_ids:
                    continue

                seen_listing_ids.add(listing_id)
                all_links.append(item)
                new_count += 1

            print(f"Bu sayfada bulunan link: {len(page_links)}")
            print(f"Bu sayfada yeni link: {new_count}")
            print(f"Toplam benzersiz link: {len(all_links)}")

            if new_count == 0:
                empty_page_count += 1
            else:
                empty_page_count = 0

            if empty_page_count >= STOP_AFTER_EMPTY_PAGE_COUNT:
                print("Pagination durdu: art arda yeni link bulunamadı.")
                break

            discovered_next_url = find_next_page_url(page, page_no)

            if discovered_next_url:
                current_page_url = discovered_next_url
            else:
                current_page_url = build_paginated_url(page_no + 1)

        context.close()
        browser.close()

    return all_links


# =========================================================
# TEK İLAN PARSER
# =========================================================

def split_location(location_text: str) -> Tuple[str, str, str]:
    parts = [p.strip() for p in str(location_text or "").split("-")]

    city = ""
    district = ""
    neighborhood = ""

    if len(parts) >= 1:
        city = parts[0]

    if len(parts) >= 2:
        district = parts[1]

    if len(parts) >= 3:
        neighborhood = parts[2]

    return city, district, neighborhood


def parse_room_count(value: Any) -> Tuple[Optional[float], Optional[float]]:
    text = str(value or "").replace(",", ".")

    match = re.search(r"(\d+(?:\.5)?)\s*\+\s*(\d+)", text)

    if not match:
        return None, None

    oda = float(match.group(1))
    salon = float(match.group(2))

    if oda.is_integer():
        oda = int(oda)

    if salon.is_integer():
        salon = int(salon)

    return oda, salon


def parse_floor(value: Any) -> Optional[int]:
    text = normalize_text(value)

    if not text:
        return None

    if "bodrum" in text:
        return -1

    if "zemin" in text or "giris" in text or "bahce" in text:
        return 0

    kot_match = re.search(r"kot\s*(\d+)", text)
    if kot_match:
        return -int(kot_match.group(1))

    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))

    return None


def map_kullanim_durumu(value: Any) -> str:
    text = normalize_text(value)

    if "bos" in text:
        return "1"

    if "kiraci" in text:
        return "2"

    if "mulk" in text or "sahibi" in text:
        return "3"

    return "0"


def map_krediye_uygunluk(value: Any) -> str:
    text = normalize_text(value)

    if "uygun degil" in text:
        return "1"

    if "uygun" in text:
        return "2"

    return "0"


def map_site_icerisinde(value: Any) -> int:
    text = normalize_text(value)

    if "evet" in text:
        return 1

    if "hayir" in text:
        return 0

    return 0


def parse_detail_table(soup: BeautifulSoup) -> Dict[str, str]:
    result = {}

    for li in soup.find_all("li"):
        spans = li.find_all("span")

        if len(spans) < 2:
            continue

        key = spans[0].get_text(" ", strip=True)
        value = spans[1].get_text(" ", strip=True)

        if not key or not value:
            continue

        value_norm = normalize_text(value)

        if re.fullmatch(r"\d+[.,]?\d*\s*m", value_norm):
            continue

        result[key] = value

    return result


def find_price(soup: BeautifulSoup, full_text: str) -> Optional[int]:
    for span in soup.find_all("span"):
        txt = span.get_text(" ", strip=True)

        if "TL" in txt:
            num = safe_number(txt, None)

            if num and num >= 100000:
                return int(num)

    match = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{6,})\s*TL", full_text)

    if match:
        num = safe_number(match.group(1), None)

        if num:
            return int(num)

    return None


def find_location_text(soup: BeautifulSoup, full_text: str) -> str:
    for span in soup.find_all("span"):
        txt = span.get_text(" ", strip=True)

        if " - " in txt and "Mahallesi" in txt:
            return txt

    match = re.search(
        r"(İstanbul\s*-\s*[A-Za-zÇĞİÖŞÜçğıöşü\s]+\s*-\s*[A-Za-zÇĞİÖŞÜçğıöşü\s]+Mahallesi)",
        full_text,
    )

    if match:
        return match.group(1).strip()

    return ""


def find_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")

    if h1:
        return clean_title(h1.get_text(" ", strip=True))

    if soup.title:
        return clean_title(soup.title.get_text(" ", strip=True))

    return "Emlakjet Satılık Daire"


def empty_poi_fields() -> Dict[str, Any]:
    result = {}

    categories = ["ulasim", "egitim", "market", "kafe_restoran", "saglik"]

    for category in categories:
        for i in range(1, 4):
            result[f"{category}_{i}_ad"] = None

    for category in categories:
        for i in range(1, 4):
            result[f"{category}_{i}_mesafe"] = None

    return result


def parse_poi_from_html(soup: BeautifulSoup) -> Dict[str, Any]:
    output = {}

    title_to_key = {
        "ulasim": "ulasim",
        "ulaşım": "ulasim",
        "egitim kurumlari": "egitim",
        "eğitim kurumları": "egitim",
        "marketler": "market",
        "kafeler/restoranlar": "kafe_restoran",
        "saglik kurumlari": "saglik",
        "sağlık kurumları": "saglik",
    }

    for span in soup.find_all("span"):
        title_text = span.get_text(" ", strip=True)
        normalized_title = normalize_text(title_text)

        category_key = None

        for title_name, mapped_key in title_to_key.items():
            if normalized_title == normalize_text(title_name):
                category_key = mapped_key
                break

        if not category_key:
            continue

        poi_card = span

        for _ in range(8):
            if poi_card is None:
                break

            poi_card = poi_card.parent

            if poi_card and poi_card.find_all("li"):
                break

        if poi_card is None:
            continue

        poi_items = []

        for li in poi_card.find_all("li"):
            spans = li.find_all("span")

            if len(spans) < 2:
                continue

            name = spans[0].get_text(" ", strip=True)
            distance_text = spans[1].get_text(" ", strip=True)

            distance = safe_meter(distance_text, None)

            if name and distance is not None:
                poi_items.append((name, distance))

        if not poi_items:
            continue

        if f"{category_key}_1_ad" in output:
            continue

        for idx, (name, distance) in enumerate(poi_items[:3], start=1):
            output[f"{category_key}_{idx}_ad"] = name
            output[f"{category_key}_{idx}_mesafe"] = distance

    return output


def build_houseai_listing(detail_url: str, html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    title = find_title(soup)
    price = find_price(soup, full_text)

    location_text = find_location_text(soup, full_text)
    city, district, neighborhood = split_location(location_text)

    table = parse_detail_table(soup)

    oda, salon = parse_room_count(table.get("Oda Sayısı"))

    net_m2 = to_int_or_none(table.get("Net Metrekare"))
    brut_m2 = to_int_or_none(table.get("Brüt Metrekare"))

    listing = {
        "id": None,
        "title": title,
        "district": district,
        "neighborhood": neighborhood,
        "price": price,
        "predictedPrice": 0,
        "lat": None,
        "lng": None,
        "status": "normal",
        "net_metrekare": net_m2,
        "brut_metrekare": brut_m2,
        "oda": oda,
        "salon": salon,
        "binanin_yasi": table.get("Binanın Yaşı", ""),
        "binanin_kat_sayisi": to_int_or_none(table.get("Binanın Kat Sayısı")),
        "bulundugu_kat_numeric": parse_floor(table.get("Bulunduğu Kat")),
        "isitma_tipi": table.get("Isıtma Tipi", ""),
        "kullanim_durumu": map_kullanim_durumu(table.get("Kullanım Durumu", "")),
        "krediye_uygunluk": map_krediye_uygunluk(table.get("Krediye Uygunluk", "")),
        "tapu_durumu": table.get("Tapu Durumu", ""),
        "site_icerisinde": map_site_icerisinde(table.get("Site İçerisinde", "")),
        "banyo_sayisi": to_int_or_none(table.get("Banyo Sayısı")),
    }

    listing.update(empty_poi_fields())

    poi_from_html = parse_poi_from_html(soup)

    if poi_from_html:
        listing.update(poi_from_html)
        print("POI HTML'den çekildi.")
    else:
        print("POI HTML'de bulunamadı.")

    return listing


def scrape_single_listing(detail_url: str) -> Dict[str, Any]:
    html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1200},
        )

        page = context.new_page()

        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(30000)

        def block_heavy_resources(route):
            resource_type = route.request.resource_type

            if resource_type in ["image", "media", "font"]:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", block_heavy_resources)

        try:
            print(f"İlan sayfası açılıyor: {detail_url}")

            page.goto(
                detail_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(2500)
            html = page.content()

        finally:
            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass

    if not html:
        raise RuntimeError("Sayfa HTML içeriği alınamadı.")

    return build_houseai_listing(detail_url, html)


# =========================================================
# DUPLICATE / VALIDATION / ID
# =========================================================

def get_max_id(listings: List[Dict[str, Any]]) -> int:
    max_id = 0

    for item in listings:
        try:
            item_id = int(item.get("id", 0) or 0)
            max_id = max(max_id, item_id)
        except Exception:
            continue

    return max_id


def get_existing_source_urls(listings: List[Dict[str, Any]]) -> Set[str]:
    result = set()

    for item in listings:
        source_url = item.get("source_url")

        if source_url:
            result.add(str(source_url).strip())

    return result


def get_existing_emlakjet_ids(listings: List[Dict[str, Any]]) -> Set[str]:
    result = set()

    for item in listings:
        emlakjet_id = item.get("emlakjet_listing_id")

        if emlakjet_id:
            result.add(str(emlakjet_id).strip())

    return result


def make_soft_duplicate_key(item: Dict[str, Any]) -> str:
    return "|".join([
        str(item.get("title", "")).strip().lower(),
        str(item.get("district", "")).strip().lower(),
        str(item.get("neighborhood", "")).strip().lower(),
        str(item.get("price", "")).strip(),
        str(item.get("net_metrekare", "")).strip(),
        str(item.get("oda", "")).strip(),
        str(item.get("salon", "")).strip(),
    ])


def get_existing_soft_keys(listings: List[Dict[str, Any]]) -> Set[str]:
    return {make_soft_duplicate_key(item) for item in listings}


def validate_for_houseai_listing(item: Dict[str, Any]) -> List[str]:
    errors = []

    required_fields = [
        "title",
        "district",
        "neighborhood",
        "price",
        "net_metrekare",
        "brut_metrekare",
        "oda",
        "salon",
        "binanin_yasi",
        "binanin_kat_sayisi",
        "bulundugu_kat_numeric",
        "isitma_tipi",
        "kullanim_durumu",
        "krediye_uygunluk",
        "tapu_durumu",
        "site_icerisinde",
        "banyo_sayisi",
    ]

    for field in required_fields:
        value = item.get(field)

        if value is None or value == "":
            errors.append(field)

    return errors


def add_import_metadata(item: Dict[str, Any], listing_id: str, url: str) -> Dict[str, Any]:
    item["source"] = "emlakjet"
    item["source_url"] = url
    item["emlakjet_listing_id"] = str(listing_id)

    if item.get("predictedPrice") is None:
        item["predictedPrice"] = 0

    if "lat" not in item:
        item["lat"] = None

    if "lng" not in item:
        item["lng"] = None

    if not item.get("status"):
        item["status"] = "normal"

    return item


# =========================================================
# KOORDİNAT DOLDURMA
# =========================================================

def is_valid_coord(lat: Any, lng: Any) -> bool:
    try:
        lat = float(lat)
        lng = float(lng)

        return 40.0 <= lat <= 42.0 and 27.0 <= lng <= 30.5
    except Exception:
        return False


def build_neighborhood_coordinate_map(
    listings: List[Dict[str, Any]]
) -> Dict[Tuple[str, str], Dict[str, float]]:
    grouped = {}

    for item in listings:
        district = normalize_text(item.get("district"))
        neighborhood = normalize_text(item.get("neighborhood"))

        lat = item.get("lat")
        lng = item.get("lng")

        if not district or not neighborhood:
            continue

        if not is_valid_coord(lat, lng):
            continue

        key = (district, neighborhood)

        if key not in grouped:
            grouped[key] = {
                "lat_values": [],
                "lng_values": [],
            }

        grouped[key]["lat_values"].append(float(lat))
        grouped[key]["lng_values"].append(float(lng))

    result = {}

    for key, values in grouped.items():
        result[key] = {
            "lat": sum(values["lat_values"]) / len(values["lat_values"]),
            "lng": sum(values["lng_values"]) / len(values["lng_values"]),
            "count": len(values["lat_values"]),
        }

    return result


def build_district_coordinate_map(
    listings: List[Dict[str, Any]]
) -> Dict[str, Dict[str, float]]:
    grouped = {}

    for item in listings:
        district = normalize_text(item.get("district"))

        lat = item.get("lat")
        lng = item.get("lng")

        if not district:
            continue

        if not is_valid_coord(lat, lng):
            continue

        if district not in grouped:
            grouped[district] = {
                "lat_values": [],
                "lng_values": [],
            }

        grouped[district]["lat_values"].append(float(lat))
        grouped[district]["lng_values"].append(float(lng))

    result = {}

    for district, values in grouped.items():
        result[district] = {
            "lat": sum(values["lat_values"]) / len(values["lat_values"]),
            "lng": sum(values["lng_values"]) / len(values["lng_values"]),
            "count": len(values["lat_values"]),
        }

    return result


def fill_missing_coordinates_in_memory(listings: List[Dict[str, Any]]) -> int:
    neighborhood_map = build_neighborhood_coordinate_map(listings)
    district_map = build_district_coordinate_map(listings)

    updated_count = 0

    for item in listings:
        if is_valid_coord(item.get("lat"), item.get("lng")):
            continue

        district = normalize_text(item.get("district"))
        neighborhood = normalize_text(item.get("neighborhood"))

        neighborhood_key = (district, neighborhood)

        if neighborhood_key in neighborhood_map:
            coord = neighborhood_map[neighborhood_key]

            item["lat"] = coord["lat"]
            item["lng"] = coord["lng"]
            item["coord_source"] = "neighborhood_average"
            item["coord_reference_count"] = coord["count"]

            updated_count += 1

        elif district in district_map:
            coord = district_map[district]

            item["lat"] = coord["lat"]
            item["lng"] = coord["lng"]
            item["coord_source"] = "district_average"
            item["coord_reference_count"] = coord["count"]

            updated_count += 1

    return updated_count


# =========================================================
# HTML RAPOR
# =========================================================

def valid_coord(item: Dict[str, Any]) -> bool:
    return is_valid_coord(item.get("lat"), item.get("lng"))


def build_stats(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    prices = []

    for item in items:
        try:
            price = float(item.get("price") or 0)
            if price > 0:
                prices.append(price)
        except Exception:
            pass

    districts = {}

    for item in items:
        district = item.get("district") or "Bilinmiyor"
        districts[district] = districts.get(district, 0) + 1

    return {
        "count": len(items),
        "with_coord": sum(1 for item in items if valid_coord(item)),
        "avg_price": statistics.mean(prices) if prices else 0,
        "min_price": min(prices) if prices else 0,
        "max_price": max(prices) if prices else 0,
        "districts": districts,
    }


def generate_report(items: List[Dict[str, Any]]) -> str:
    stats = build_stats(items)

    markers = []

    for item in items:
        if not valid_coord(item):
            continue

        markers.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "district": item.get("district"),
            "neighborhood": item.get("neighborhood"),
            "price": item.get("price"),
            "price_text": format_price(item.get("price")),
            "lat": item.get("lat"),
            "lng": item.get("lng"),
            "oda": item.get("oda"),
            "salon": item.get("salon"),
            "net_metrekare": item.get("net_metrekare"),
            "source_url": item.get("source_url", ""),
        })

    table_rows = ""

    for item in items:
        source_url = item.get("source_url", "")

        if source_url:
            link_html = f'<a href="{html_escape(source_url)}" target="_blank">İlana Git</a>'
        else:
            link_html = "-"

        coord_text = "Var" if valid_coord(item) else "Yok"

        table_rows += f"""
        <tr>
          <td>{html_escape(item.get("id"))}</td>
          <td>{html_escape(item.get("emlakjet_listing_id"))}</td>
          <td class="title-cell">{html_escape(item.get("title"))}</td>
          <td>{html_escape(item.get("district"))}</td>
          <td>{html_escape(item.get("neighborhood"))}</td>
          <td>{html_escape(item.get("oda"))}+{html_escape(item.get("salon"))}</td>
          <td>{html_escape(item.get("net_metrekare"))} m²</td>
          <td>{format_price(item.get("price"))}</td>
          <td>{coord_text}</td>
          <td>{link_html}</td>
        </tr>
        """

    district_cards = ""

    for district, count in sorted(stats["districts"].items(), key=lambda x: x[0]):
        district_cards += f"""
        <div class="district-card">
          <strong>{html_escape(district)}</strong>
          <span>{count} ilan</span>
        </div>
        """

    markers_json = json.dumps(markers, ensure_ascii=False)

    html = f"""
<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <title>HouseAI Emlakjet Import Raporu</title>

  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  />

  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f4f6fb;
      color: #172033;
    }}

    header {{
      padding: 24px;
      background: linear-gradient(135deg, #111827, #1f2937);
      color: white;
    }}

    header h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}

    header p {{
      margin: 0;
      opacity: 0.85;
    }}

    .container {{
      padding: 24px;
      display: grid;
      gap: 20px;
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 16px;
    }}

    .stat-card {{
      background: white;
      padding: 18px;
      border-radius: 16px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.06);
    }}

    .stat-card span {{
      display: block;
      color: #6b7280;
      font-size: 13px;
      margin-bottom: 8px;
    }}

    .stat-card strong {{
      font-size: 22px;
    }}

    .section {{
      background: white;
      padding: 20px;
      border-radius: 18px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.06);
    }}

    .section h2 {{
      margin: 0 0 16px;
      font-size: 20px;
    }}

    #map {{
      width: 100%;
      height: 460px;
      border-radius: 16px;
      overflow: hidden;
    }}

    .district-grid {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    .district-card {{
      padding: 10px 14px;
      border-radius: 12px;
      background: #f3f4f6;
      display: flex;
      gap: 8px;
      align-items: center;
    }}

    .district-card span {{
      color: #6b7280;
      font-size: 13px;
    }}

    .toolbar {{
      display: flex;
      gap: 12px;
      margin-bottom: 14px;
    }}

    .toolbar input {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid #d1d5db;
      outline: none;
      font-size: 14px;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}

    th, td {{
      padding: 12px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      vertical-align: top;
    }}

    th {{
      background: #f9fafb;
      color: #374151;
      position: sticky;
      top: 0;
      z-index: 1;
    }}

    .table-wrap {{
      max-height: 600px;
      overflow: auto;
      border: 1px solid #e5e7eb;
      border-radius: 14px;
    }}

    .title-cell {{
      max-width: 360px;
      line-height: 1.35;
    }}

    a {{
      color: #2563eb;
      text-decoration: none;
      font-weight: 600;
    }}

    .note {{
      padding: 12px 14px;
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 12px;
      color: #9a3412;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>HouseAI Emlakjet Import Raporu</h1>
    <p>Son çalıştırmada eklenen yeni ilanları tablo ve harita üzerinde görüntüleme ekranı</p>
  </header>

  <div class="container">
    <div class="stats-grid">
      <div class="stat-card">
        <span>Bu çalıştırmada eklenen ilan</span>
        <strong>{stats["count"]}</strong>
      </div>

      <div class="stat-card">
        <span>Koordinatı olan ilan</span>
        <strong>{stats["with_coord"]}</strong>
      </div>

      <div class="stat-card">
        <span>Ortalama fiyat</span>
        <strong>{format_price(stats["avg_price"])}</strong>
      </div>

      <div class="stat-card">
        <span>Fiyat aralığı</span>
        <strong>{format_price(stats["min_price"])} - {format_price(stats["max_price"])}</strong>
      </div>
    </div>

    <div class="section">
      <h2>İlçe Dağılımı</h2>
      <div class="district-grid">
        {district_cards}
      </div>
    </div>

    <div class="section">
      <h2>Harita Görünümü</h2>
      <div class="note">
        Harita yüklenmezse internet bağlantısı veya Leaflet CDN engeli olabilir. Tablo yine çalışır.
      </div>
      <br>
      <div id="map"></div>
    </div>

    <div class="section">
      <h2>Import Edilen İlanlar</h2>

      <div class="toolbar">
        <input id="searchInput" type="text" placeholder="Başlık, ilçe, mahalle, oda tipi veya fiyat ara..." />
      </div>

      <div class="table-wrap">
        <table id="listingsTable">
          <thead>
            <tr>
              <th>ID</th>
              <th>Emlakjet ID</th>
              <th>Başlık</th>
              <th>İlçe</th>
              <th>Mahalle</th>
              <th>Oda</th>
              <th>Net m²</th>
              <th>Fiyat</th>
              <th>Koordinat</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <script>
    const markers = {markers_json};

    const map = L.map("map").setView([41.0082, 28.9784], 10);

    L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap"
    }}).addTo(map);

    const markerGroup = L.featureGroup();

    markers.forEach(item => {{
      const marker = L.marker([item.lat, item.lng]);

      marker.bindPopup(`
        <strong>${{item.title || "İlan"}}</strong><br>
        ${{item.district || ""}} / ${{item.neighborhood || ""}}<br>
        ${{item.oda || ""}}+${{item.salon || ""}} | ${{item.net_metrekare || ""}} m²<br>
        <strong>${{item.price_text}}</strong><br>
        ${{item.source_url ? `<a href="${{item.source_url}}" target="_blank">Emlakjet ilanını aç</a>` : ""}}
      `);

      marker.addTo(markerGroup);
    }});

    markerGroup.addTo(map);

    if (markers.length > 0) {{
      map.fitBounds(markerGroup.getBounds(), {{
        padding: [30, 30]
      }});
    }}

    setTimeout(() => {{
      map.invalidateSize();

      if (markers.length > 0) {{
        map.fitBounds(markerGroup.getBounds(), {{
          padding: [30, 30]
        }});
      }}
    }}, 500);

    const searchInput = document.getElementById("searchInput");
    const rows = Array.from(document.querySelectorAll("#listingsTable tbody tr"));

    searchInput.addEventListener("input", () => {{
      const query = searchInput.value.toLowerCase();

      rows.forEach(row => {{
        const text = row.innerText.toLowerCase();
        row.style.display = text.includes(query) ? "" : "none";
      }});
    }});
  </script>
</body>
</html>
"""

    return html


def generate_and_open_report(added_items: List[Dict[str, Any]]) -> None:
    html = generate_report(added_items)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")

    print("\nHTML rapor oluşturuldu:")
    print(REPORT_PATH)

    if OPEN_REPORT_AFTER_RUN:
        webbrowser.open(REPORT_PATH.as_uri())


# =========================================================
# ANA PIPELINE
# =========================================================

def run_pipeline() -> None:
    print("\n========================================================")
    print("HOUSEAI OTOMATİK EMLAKJET VERİ ÇEKME")
    print("Başlangıç:", now_text())
    print("========================================================\n")

    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if not LISTINGS_PATH.exists():
        print("HATA: listings.json bulunamadı.")
        print("Beklenen yol:", LISTINGS_PATH)
        return

    listings = load_json(LISTINGS_PATH, [])

    if not isinstance(listings, list):
        print("HATA: listings.json liste formatında değil.")
        return

    print("Mevcut ilan sayısı:", len(listings))

    print("\n1) Son 24 saat ilan linkleri çekiliyor...")
    links = scrape_listing_links()
    save_json(LINKS_OUTPUT_PATH, links)

    print("\nToplam bulunan benzersiz ilan linki:", len(links))
    print("Link dosyası:", LINKS_OUTPUT_PATH)

    selected_links = links

    existing_source_urls = get_existing_source_urls(listings)
    existing_emlakjet_ids = get_existing_emlakjet_ids(listings)
    existing_soft_keys = get_existing_soft_keys(listings)

    next_id = get_max_id(listings) + 1

    pending = []
    rejected = []
    skipped = []

    print("\n2) İlan detayları çekiliyor...")
    print("İşlenecek ilan sayısı:", len(selected_links))
    print("Başlangıç yeni id:", next_id)

    for index, link_item in enumerate(selected_links, start=1):
        listing_id = str(link_item.get("listing_id", "")).strip()
        url = str(link_item.get("url", "")).strip()

        print("\n--------------------------------------------------------")
        print(f"[{index}/{len(selected_links)}] İşleniyor: {listing_id}")
        print(url)

        if not listing_id or not url:
            rejected.append({
                "listing_id": listing_id,
                "url": url,
                "reason": "listing_id veya url boş",
                "item": None,
            })
            print("Reddedildi: listing_id veya url boş")
            continue

        if url in existing_source_urls:
            skipped.append({
                "listing_id": listing_id,
                "url": url,
                "reason": "source_url duplicate",
            })
            print("Atlandı: source_url duplicate")
            continue

        if listing_id in existing_emlakjet_ids:
            skipped.append({
                "listing_id": listing_id,
                "url": url,
                "reason": "emlakjet_listing_id duplicate",
            })
            print("Atlandı: emlakjet_listing_id duplicate")
            continue

        try:
            item = scrape_single_listing(url)
            item = add_import_metadata(item, listing_id, url)

            soft_key = make_soft_duplicate_key(item)

            if soft_key in existing_soft_keys:
                skipped.append({
                    "listing_id": listing_id,
                    "url": url,
                    "reason": "soft duplicate",
                    "item": item,
                })
                print("Atlandı: soft duplicate")
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            errors = validate_for_houseai_listing(item)

            if errors:
                rejected.append({
                    "listing_id": listing_id,
                    "url": url,
                    "reason": "Eksik/geçersiz alan var",
                    "errors": errors,
                    "item": item,
                })

                print("Reddedildi. Eksik alanlar:", errors)
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            item["id"] = next_id
            next_id += 1

            pending.append(item)

            existing_source_urls.add(url)
            existing_emlakjet_ids.add(listing_id)
            existing_soft_keys.add(soft_key)

            print("Başarılı.")
            print("Başlık:", item.get("title"))
            print("Konum:", item.get("district"), "/", item.get("neighborhood"))
            print("Fiyat:", item.get("price"))

        except Exception as error:
            rejected.append({
                "listing_id": listing_id,
                "url": url,
                "reason": str(error),
                "item": None,
            })

            print("Hata oluştu:", error)

        time.sleep(REQUEST_DELAY_SECONDS)

    save_json(PENDING_OUTPUT_PATH, pending)
    save_json(REJECTED_OUTPUT_PATH, rejected)
    save_json(SKIPPED_OUTPUT_PATH, skipped)

    added = []

    if pending:
        print("\n3) listings.json güncelleniyor...")

        backup_path = backup_file(LISTINGS_PATH, "backup")
        if backup_path:
            print("Backup oluşturuldu:", backup_path)

        listings.extend(pending)

        print("\n4) Eksik koordinatlar dolduruluyor...")
        coord_filled_count = fill_missing_coordinates_in_memory(listings)

        save_json(LISTINGS_PATH, listings)

        added = pending
        save_json(ADDED_OUTPUT_PATH, added)

        print("Eklenen ilan sayısı:", len(added))
        print("Koordinatı doldurulan ilan sayısı:", coord_filled_count)
        print("Yeni toplam ilan sayısı:", len(listings))

    else:
        print("\n3) Eklenecek yeni ilan yok.")
        save_json(ADDED_OUTPUT_PATH, [])

    summary = {
        "run_at": now_text(),
        "links_found": len(links),
        "links_processed": len(selected_links),
        "added_count": len(added),
        "rejected_count": len(rejected),
        "skipped_count": len(skipped),
        "listings_path": str(LISTINGS_PATH),
        "links_output_path": str(LINKS_OUTPUT_PATH),
        "pending_output_path": str(PENDING_OUTPUT_PATH),
        "added_output_path": str(ADDED_OUTPUT_PATH),
        "rejected_output_path": str(REJECTED_OUTPUT_PATH),
        "skipped_output_path": str(SKIPPED_OUTPUT_PATH),
    }

    save_json(LAST_RUN_OUTPUT_PATH, summary)

    print("\n================ SONUÇ ================")
    print("Bulunan link:", len(links))
    print("İşlenen link:", len(selected_links))
    print("Eklenen ilan:", len(added))
    print("Reddedilen:", len(rejected))
    print("Atlanan:", len(skipped))
    print("Bitiş:", now_text())

    print("\nÇalışma özeti:")
    print(LAST_RUN_OUTPUT_PATH)

    generate_and_open_report(added)

    print("\nİşlem tamamlandı.")


if __name__ == "__main__":
    run_pipeline()