let selectedLocation = null;

function normalizeText(text) {
  return String(text || "")
    .toLowerCase()
    .replaceAll("ı", "i")
    .replaceAll("ğ", "g")
    .replaceAll("ü", "u")
    .replaceAll("ş", "s")
    .replaceAll("ö", "o")
    .replaceAll("ç", "c")
    .replace(/\s+/g, " ")
    .trim();
}

function readSelectedLocation() {
  const possibleKeys = [
    "selectedHomeLocation",
    "selectedLocationData",
    "selectedLocation",
  ];

  for (const key of possibleKeys) {
    const raw = localStorage.getItem(key);

    if (!raw) continue;

    try {
      const parsed = JSON.parse(raw);

      if (parsed && parsed.district && parsed.neighborhood) {
        return {
          district: parsed.district,
          neighborhood: parsed.neighborhood,
          lat: parsed.lat ?? parsed.latitude ?? null,
          lng: parsed.lng ?? parsed.longitude ?? null,
        };
      }
    } catch (error) {
      console.warn(`${key} parse edilemedi`, error);
    }
  }

  return null;
}

const locationTitle = document.getElementById("location-title");
const locationWarning = document.getElementById("location-warning");
const latValue = document.getElementById("lat-value");
const lngValue = document.getElementById("lng-value");

const districtInput = document.getElementById("district");
const neighborhoodInput = document.getElementById("neighborhood");

function setValue(id, value) {
  const element = document.getElementById(id);

  if (!element) return;

  if (
    value === undefined ||
    value === null ||
    value === "" ||
    Number.isNaN(value)
  ) {
    element.value = "";
    return;
  }

  element.value = value;
}

function toNumber(value) {
  if (value === undefined || value === null || value === "") return "";

  const text = String(value).replace(",", ".");
  const match = text.match(/\d+(\.\d+)?/);

  if (!match) return "";

  return Number(match[0]);
}

function getNumberValue(id) {
  const element = document.getElementById(id);

  if (!element) return null;

  const value = element.value;

  if (value === "") return null;

  return Number(value);
}

function getTextValue(id) {
  const element = document.getElementById(id);

  if (!element) return null;

  const value = element.value.trim();

  return value === "" ? null : value;
}

function fillBasicLocation() {
  selectedLocation = readSelectedLocation();

  if (!selectedLocation) {
    locationTitle.textContent = "Konum bulunamadı";
    latValue.textContent = "-";
    lngValue.textContent = "-";

    districtInput.value = "";
    neighborhoodInput.value = "";

    locationWarning.classList.add("show");
    return;
  }

  locationWarning.classList.remove("show");

  locationTitle.textContent = `${selectedLocation.district} / ${selectedLocation.neighborhood}`;

  if (selectedLocation.lat !== null && selectedLocation.lat !== undefined) {
    latValue.textContent = Number(selectedLocation.lat).toFixed(5);
  } else {
    latValue.textContent = "-";
  }

  if (selectedLocation.lng !== null && selectedLocation.lng !== undefined) {
    lngValue.textContent = Number(selectedLocation.lng).toFixed(5);
  } else {
    lngValue.textContent = "-";
  }

  districtInput.value = selectedLocation.district;
  neighborhoodInput.value = selectedLocation.neighborhood;
}

function degreesToRadians(degrees) {
  return degrees * (Math.PI / 180);
}

function calculateDistanceKm(lat1, lng1, lat2, lng2) {
  const earthRadiusKm = 6371;

  const dLat = degreesToRadians(lat2 - lat1);
  const dLng = degreesToRadians(lng2 - lng1);

  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(degreesToRadians(lat1)) *
      Math.cos(degreesToRadians(lat2)) *
      Math.sin(dLng / 2) ** 2;

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

  return earthRadiusKm * c;
}

function updateDistanceLabel(inputId, baseLabel, poiName) {
  const input = document.getElementById(inputId);

  if (!input) return;

  const field = input.closest(".field");

  if (!field) return;

  const label = field.querySelector("label");

  if (!label) return;

  if (poiName) {
    label.innerHTML = `${baseLabel}<br><small>${poiName}</small>`;
  } else {
    label.innerHTML = baseLabel;
  }
}

function fillPoi(prefix, labelText, listing) {
  const mesafeId = `${prefix}_mesafe`;
  const adKey = `${prefix}_ad`;
  const mesafeKey = `${prefix}_mesafe`;

  setValue(mesafeId, toNumber(listing[mesafeKey]));
  updateDistanceLabel(mesafeId, labelText, listing[adKey]);
}

function fillProximityWithListing(listing) {
  fillPoi("ulasim_1", "Ulaşım 1 Mesafe", listing);
  fillPoi("ulasim_2", "Ulaşım 2 Mesafe", listing);
  fillPoi("ulasim_3", "Ulaşım 3 Mesafe", listing);

  fillPoi("egitim_1", "Eğitim 1 Mesafe", listing);
  fillPoi("egitim_2", "Eğitim 2 Mesafe", listing);
  fillPoi("egitim_3", "Eğitim 3 Mesafe", listing);

  fillPoi("market_1", "Market 1 Mesafe", listing);
  fillPoi("market_2", "Market 2 Mesafe", listing);
  fillPoi("market_3", "Market 3 Mesafe", listing);

  fillPoi("kafe_restoran_1", "Kafe 1 Mesafe", listing);
  fillPoi("kafe_restoran_2", "Kafe 2 Mesafe", listing);
  fillPoi("kafe_restoran_3", "Kafe 3 Mesafe", listing);

  fillPoi("saglik_1", "Sağlık 1 Mesafe", listing);
  fillPoi("saglik_2", "Sağlık 2 Mesafe", listing);
  fillPoi("saglik_3", "Sağlık 3 Mesafe", listing);
}

async function fillNearestListingData() {
  if (!selectedLocation) {
    console.warn("Konum yok. Yakınlık bilgileri otomatik doldurulmadı.");
    return;
  }

  if (selectedLocation.lat === null || selectedLocation.lng === null) {
    console.warn("Lat/Lng yok. Yakınlık bilgileri otomatik doldurulmadı.");
    return;
  }

  try {
    const response = await fetch("listings.json");

    if (!response.ok) {
      throw new Error("listings.json yüklenemedi.");
    }

    const listings = await response.json();

    const sameNeighborhoodListings = listings.filter((item) => {
      return (
        normalizeText(item.district) ===
          normalizeText(selectedLocation.district) &&
        normalizeText(item.neighborhood) ===
          normalizeText(selectedLocation.neighborhood)
      );
    });

    const sameDistrictListings = listings.filter((item) => {
      return (
        normalizeText(item.district) ===
        normalizeText(selectedLocation.district)
      );
    });

    const searchList =
      sameNeighborhoodListings.length > 0
        ? sameNeighborhoodListings
        : sameDistrictListings.length > 0
          ? sameDistrictListings
          : listings;

    let nearestListing = null;
    let minDistance = Infinity;

    searchList.forEach((item) => {
      const itemLat = Number(item.lat);
      const itemLng = Number(item.lng);

      if (!itemLat || !itemLng) return;

      const distance = calculateDistanceKm(
        Number(selectedLocation.lat),
        Number(selectedLocation.lng),
        itemLat,
        itemLng,
      );

      if (distance < minDistance) {
        minDistance = distance;
        nearestListing = item;
      }
    });

    if (!nearestListing) {
      console.warn("En yakın ilan bulunamadı.");
      return;
    }

    fillProximityWithListing(nearestListing);

    console.log("Yakınlık bilgileri en yakın ilandan alındı:", nearestListing);
  } catch (error) {
    console.error(error);
    alert(
      "listings.json okunamadı. Dosyanın predict.html ile aynı klasörde olduğundan emin ol.",
    );
  }
}

function buildModelInput() {
  const oda = getNumberValue("oda");
  const salon = getNumberValue("salon");
  const toplamOda = oda !== null && salon !== null ? oda + salon : null;

  return {
    ilce: getTextValue("district"),
    mahalle: getTextValue("neighborhood"),

    net_metrekare: getNumberValue("net_metrekare"),
    brut_metrekare: getNumberValue("brut_metrekare"),

    oda: oda,
    salon: salon,
    toplam_oda: toplamOda,

    binanin_yasi: getTextValue("binanin_yasi"),
    binanin_kat_sayisi: getNumberValue("binanin_kat_sayisi"),
    bulundugu_kat_numeric: getNumberValue("bulundugu_kat_numeric"),

    isitma_tipi: getTextValue("isitma_tipi"),
    kullanim_durumu: getNumberValue("kullanim_durumu"),
    krediye_uygunluk: getNumberValue("krediye_uygunluk"),
    tapu_durumu: getTextValue("tapu_durumu"),
    site_icerisinde: getNumberValue("site_icerisinde"),
    banyo_sayisi: getNumberValue("banyo_sayisi"),

    ulasim_1_mesafe: getNumberValue("ulasim_1_mesafe"),
    ulasim_2_mesafe: getNumberValue("ulasim_2_mesafe"),
    ulasim_3_mesafe: getNumberValue("ulasim_3_mesafe"),

    egitim_1_mesafe: getNumberValue("egitim_1_mesafe"),
    egitim_2_mesafe: getNumberValue("egitim_2_mesafe"),
    egitim_3_mesafe: getNumberValue("egitim_3_mesafe"),

    market_1_mesafe: getNumberValue("market_1_mesafe"),
    market_2_mesafe: getNumberValue("market_2_mesafe"),
    market_3_mesafe: getNumberValue("market_3_mesafe"),

    kafe_restoran_1_mesafe: getNumberValue("kafe_restoran_1_mesafe"),
    kafe_restoran_2_mesafe: getNumberValue("kafe_restoran_2_mesafe"),
    kafe_restoran_3_mesafe: getNumberValue("kafe_restoran_3_mesafe"),

    saglik_1_mesafe: getNumberValue("saglik_1_mesafe"),
    saglik_2_mesafe: getNumberValue("saglik_2_mesafe"),
    saglik_3_mesafe: getNumberValue("saglik_3_mesafe"),
  };
}

function validateModelInput(modelInput) {
  const missingFields = [];

  if (!modelInput.ilce) missingFields.push("İlçe");
  if (!modelInput.mahalle) missingFields.push("Mahalle");
  if (!modelInput.net_metrekare) missingFields.push("Net m²");
  if (!modelInput.brut_metrekare) missingFields.push("Brüt m²");
  if (modelInput.oda === null) missingFields.push("Oda");
  if (modelInput.salon === null) missingFields.push("Salon");
  if (!modelInput.binanin_yasi) missingFields.push("Bina Yaşı");
  if (!modelInput.binanin_kat_sayisi) missingFields.push("Binanın Kat Sayısı");
  if (!modelInput.bulundugu_kat_numeric) missingFields.push("Bulunduğu Kat");
  if (!modelInput.isitma_tipi) missingFields.push("Isıtma Tipi");
  if (modelInput.kullanim_durumu === null)
    missingFields.push("Kullanım Durumu");
  if (modelInput.krediye_uygunluk === null)
    missingFields.push("Krediye Uygunluk");
  if (!modelInput.tapu_durumu) missingFields.push("Tapu Durumu");
  if (modelInput.site_icerisinde === null)
    missingFields.push("Site İçerisinde");
  if (modelInput.banyo_sayisi === null) missingFields.push("Banyo Sayısı");

  return missingFields;
}

async function runBasicPrediction(modelInput) {
  try {
    const response = await fetch("/api/basic-price-predict", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(modelInput),
    });

    if (!response.ok) {
      throw new Error("Basic prediction API hata verdi.");
    }

    return await response.json();
  } catch (error) {
    console.warn(
      "Basic prediction API çalışmadı. Sadece JSON kaydedildi.",
      error,
    );

    return {
      success: false,
      message:
        "Basic prediction API henüz bağlı değil. Sadece model input JSON hazırlandı.",
      input: modelInput,
    };
  }
}

document
  .getElementById("property-form")
  .addEventListener("submit", async function (event) {
    event.preventDefault();

    const modelInput = buildModelInput();

    const missingFields = validateModelInput(modelInput);

    if (missingFields.length > 0) {
      const confirmContinue = confirm(
        "Bazı alanlar eksik:\n\n" +
          missingFields.join(", ") +
          "\n\nYine de JSON hazırlansın mı?",
      );

      if (!confirmContinue) return;
    }

    document.getElementById("output-json").textContent = JSON.stringify(
      modelInput,
      null,
      2,
    );

    localStorage.setItem("lastPropertyInput", JSON.stringify(modelInput));

    const predictionResult = await runBasicPrediction(modelInput);

    localStorage.setItem(
      "lastPredictionResult",
      JSON.stringify(predictionResult),
    );

    const predictionPackage = {
      modelInput: modelInput,
      predictionResult: predictionResult,
      createdAt: new Date().toISOString(),
    };

    localStorage.setItem(
      "lastPredictionPackage",
      JSON.stringify(predictionPackage),
    );

    document.getElementById("output-json").textContent =
      "MODEL INPUT JSON\n" +
      "-----------------------------\n" +
      JSON.stringify(modelInput, null, 2) +
      "\n\n" +
      "BASIC PRICE PREDICTION RESULT\n" +
      "-----------------------------\n" +
      JSON.stringify(predictionResult, null, 2);

    const goSellerButton = document.getElementById("go-seller-page-btn");

    if (goSellerButton) {
      goSellerButton.disabled = false;
    }
  });

const goSellerButton = document.getElementById("go-seller-page-btn");

if (goSellerButton) {
  goSellerButton.addEventListener("click", function () {
    const savedInput = localStorage.getItem("lastPropertyInput");

    if (!savedInput) {
      alert("Önce tahmin verisini hazırlamalısın.");
      return;
    }

    window.location.href = "seller.html";
  });
}

fillBasicLocation();
fillNearestListingData();
