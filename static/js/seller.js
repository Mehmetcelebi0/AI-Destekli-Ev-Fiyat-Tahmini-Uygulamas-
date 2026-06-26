let sellerState = {
  modelInput: null,
  predictionResult: null,
  analysis: null,
  similarListings: [],
};

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

function normalizeNeighborhood(text) {
  return normalizeText(text).replace(" mahallesi", "").trim();
}

function safeNumber(value, fallback = 0) {
  const numberValue = Number(value);

  if (Number.isNaN(numberValue)) return fallback;

  return numberValue;
}

function formatPrice(price) {
  return Math.round(Number(price || 0)).toLocaleString("tr-TR") + " TL";
}

function getListingPrice(item) {
  return safeNumber(item.price);
}

function getNetM2(item) {
  return safeNumber(item.net_metrekare);
}

function getRoom(item) {
  return safeNumber(item.oda);
}

function getSalon(item) {
  return safeNumber(item.salon);
}

function readStorageData() {
  const packageRaw = localStorage.getItem("lastPredictionPackage");
  const inputRaw = localStorage.getItem("lastPropertyInput");
  const predictionRaw = localStorage.getItem("lastPredictionResult");

  let modelInput = null;
  let predictionResult = null;

  if (packageRaw) {
    try {
      const parsed = JSON.parse(packageRaw);
      modelInput = parsed.modelInput || null;
      predictionResult = parsed.predictionResult || null;
    } catch (error) {
      console.warn("lastPredictionPackage okunamadı", error);
    }
  }

  if (!modelInput && inputRaw) {
    try {
      modelInput = JSON.parse(inputRaw);
    } catch (error) {
      console.warn("lastPropertyInput okunamadı", error);
    }
  }

  if (!predictionResult && predictionRaw) {
    try {
      predictionResult = JSON.parse(predictionRaw);
    } catch (error) {
      console.warn("lastPredictionResult okunamadı", error);
    }
  }

  return {
    modelInput,
    predictionResult,
  };
}

async function loadListings() {
  try {
    const response = await fetch("listings.json");

    if (!response.ok) {
      throw new Error("listings.json yüklenemedi.");
    }

    return await response.json();
  } catch (error) {
    console.error(error);
    return [];
  }
}

function findSimilarListings(modelInput, listings) {
  const ilce = normalizeText(modelInput.ilce);
  const mahalle = normalizeNeighborhood(modelInput.mahalle);

  const oda = safeNumber(modelInput.oda, null);
  const salon = safeNumber(modelInput.salon, null);
  const netM2 = safeNumber(modelInput.net_metrekare, null);

  function isValidListing(item) {
    return getListingPrice(item) > 0 && getNetM2(item) > 0;
  }

  function sameDistrict(item) {
    return normalizeText(item.district) === ilce;
  }

  function sameNeighborhood(item) {
    return normalizeNeighborhood(item.neighborhood) === mahalle;
  }

  function sameRoom(item) {
    const roomOk = oda === null || getRoom(item) === oda;
    const salonOk = salon === null || getSalon(item) === salon;

    return roomOk && salonOk;
  }

  function similarM2(item) {
    if (!netM2) return true;

    const itemM2 = getNetM2(item);
    const lower = netM2 * 0.75;
    const upper = netM2 * 1.25;

    return itemM2 >= lower && itemM2 <= upper;
  }

  const strongMatches = listings.filter((item) => {
    return (
      isValidListing(item) &&
      sameDistrict(item) &&
      sameNeighborhood(item) &&
      sameRoom(item) &&
      similarM2(item)
    );
  });

  if (strongMatches.length >= 3) {
    return {
      matchLevel: "Aynı mahalle + aynı oda tipi + benzer m²",
      confidence: strongMatches.length >= 6 ? "Yüksek" : "Orta-Yüksek",
      listings: strongMatches,
    };
  }

  const neighborhoodRoomMatches = listings.filter((item) => {
    return (
      isValidListing(item) &&
      sameDistrict(item) &&
      sameNeighborhood(item) &&
      sameRoom(item)
    );
  });

  if (neighborhoodRoomMatches.length >= 2) {
    return {
      matchLevel: "Aynı mahalle + aynı oda tipi",
      confidence: "Orta-Yüksek",
      listings: neighborhoodRoomMatches,
    };
  }

  const neighborhoodMatches = listings.filter((item) => {
    return isValidListing(item) && sameDistrict(item) && sameNeighborhood(item);
  });

  if (neighborhoodMatches.length >= 2) {
    return {
      matchLevel: "Aynı mahalle tüm oda tipleri",
      confidence: "Orta",
      listings: neighborhoodMatches,
    };
  }

  const districtRoomMatches = listings.filter((item) => {
    return isValidListing(item) && sameDistrict(item) && sameRoom(item);
  });

  if (districtRoomMatches.length >= 2) {
    return {
      matchLevel: "Aynı ilçe + aynı oda tipi",
      confidence: "Düşük-Orta",
      listings: districtRoomMatches,
    };
  }

  const districtMatches = listings.filter((item) => {
    return isValidListing(item) && sameDistrict(item);
  });

  return {
    matchLevel: "Aynı ilçe genel veri",
    confidence: districtMatches.length >= 5 ? "Düşük-Orta" : "Düşük",
    listings: districtMatches,
  };
}

function median(values) {
  if (!values.length) return 0;

  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);

  if (sorted.length % 2 === 0) {
    return (sorted[middle - 1] + sorted[middle]) / 2;
  }

  return sorted[middle];
}

function calculateAdjustment(modelInput) {
  let multiplier = 1;
  const notes = [];

  if (safeNumber(modelInput.site_icerisinde, null) === 1) {
    multiplier *= 1.03;
    notes.push(
      "Site içerisinde olduğu için fiyat tahminine yaklaşık %3 pozitif etki eklendi.",
    );
  }

  if (safeNumber(modelInput.krediye_uygunluk, null) === 2) {
    multiplier *= 1.02;
    notes.push(
      "Krediye uygunluk satış kolaylığı sağlayabileceği için yaklaşık %2 pozitif etki eklendi.",
    );
  }

  if (normalizeText(modelInput.tapu_durumu).includes("kat mulkiyeti")) {
    multiplier *= 1.015;
    notes.push("Kat mülkiyeti tapu durumu için küçük pozitif etki uygulandı.");
  }

  const heating = normalizeText(modelInput.isitma_tipi);

  if (heating.includes("merkezi") || heating.includes("yerden")) {
    multiplier *= 1.015;
    notes.push(
      "Isıtma tipi avantajlı kabul edildiği için küçük pozitif etki uygulandı.",
    );
  }

  if (safeNumber(modelInput.banyo_sayisi, 0) >= 2) {
    multiplier *= 1.015;
    notes.push("Banyo sayısı yüksek olduğu için küçük pozitif etki uygulandı.");
  }

  const currentFloor = safeNumber(modelInput.bulundugu_kat_numeric, null);
  const totalFloor = safeNumber(modelInput.binanin_kat_sayisi, null);

  if (currentFloor !== null && totalFloor && totalFloor > 0) {
    const ratio = currentFloor / totalFloor;

    if (ratio >= 0.25 && ratio <= 0.75) {
      multiplier *= 1.01;
      notes.push(
        "Bulunduğu kat dengeli aralıkta olduğu için küçük pozitif etki uygulandı.",
      );
    }
  }

  return {
    multiplier,
    notes,
  };
}

function calculateAnalysis(modelInput, predictionResult, similarResult) {
  const listings = similarResult.listings;
  const netM2 = safeNumber(modelInput.net_metrekare);

  if (!modelInput || !netM2 || listings.length === 0) {
    return null;
  }

  const prices = listings.map(getListingPrice).filter((value) => value > 0);

  const m2Prices = listings
    .map((item) => getListingPrice(item) / getNetM2(item))
    .filter((value) => value > 0 && Number.isFinite(value));

  const avgPrice =
    prices.reduce((sum, value) => sum + value, 0) / Math.max(prices.length, 1);

  const avgM2Price =
    m2Prices.reduce((sum, value) => sum + value, 0) /
    Math.max(m2Prices.length, 1);

  const medianPrice = median(prices);
  const medianM2Price = median(m2Prices);

  const baseM2Price = avgM2Price * 0.45 + medianM2Price * 0.55;
  let estimatedPrice = baseM2Price * netM2;

  const adjustment = calculateAdjustment(modelInput);
  estimatedPrice *= adjustment.multiplier;

  if (
    predictionResult &&
    predictionResult.success &&
    predictionResult.prediction
  ) {
    estimatedPrice = safeNumber(
      predictionResult.prediction.estimated_price,
      estimatedPrice,
    );
  }

  const quickSalePrice = estimatedPrice * 0.96;
  const balancedSalePrice = estimatedPrice * 1.02;
  const highSalePrice = estimatedPrice * 1.08;
  const sixMonthPrice = estimatedPrice * 1.035;

  return {
    estimatedPrice,
    quickSalePrice,
    balancedSalePrice,
    highSalePrice,
    sixMonthPrice,

    avgPrice,
    medianPrice,
    minPrice: Math.min(...prices),
    maxPrice: Math.max(...prices),

    avgM2Price,
    medianM2Price,

    matchLevel: similarResult.matchLevel,
    confidence: similarResult.confidence,
    similarCount: listings.length,
    adjustmentNotes: adjustment.notes,
  };
}

function renderPage() {
  const input = sellerState.modelInput;
  const analysis = sellerState.analysis;

  if (!input || !analysis) {
    document.body.innerHTML = `
      <div class="error-card">
        <h1>Satış analizi için veri bulunamadı</h1>
        <p>Önce 2. sayfada ev bilgilerini girip “Tahmin Verisini Hazırla” butonuna basmalısın.</p>
        <a href="predict.html" class="back-link">Tahmin Sayfasına Dön</a>
      </div>
    `;
    return;
  }

  document.getElementById("estimated-price").textContent = formatPrice(
    analysis.estimatedPrice,
  );

  document.getElementById("confidence-text").textContent =
    `Tahmin Güveni: ${analysis.confidence}`;

  document.getElementById("property-title").textContent =
    `${input.ilce || "-"} / ${input.mahalle || "-"} ${input.oda || "-"}+${input.salon || "-"} Daire`;

  document.getElementById("property-subtitle").textContent =
    `${input.net_metrekare || "-"} m² net, ${input.brut_metrekare || "-"} m² brüt, ${input.binanin_yasi || "-"} bina yaşı`;

  const tags = [
    `Net: ${input.net_metrekare || "-"} m²`,
    `Brüt: ${input.brut_metrekare || "-"} m²`,
    `Oda: ${input.oda || "-"}+${input.salon || "-"}`,
    `Kat: ${input.bulundugu_kat_numeric || "-"}/${input.binanin_kat_sayisi || "-"}`,
    `Banyo: ${input.banyo_sayisi ?? "-"}`,
    `Isıtma: ${input.isitma_tipi || "-"}`,
    `Tapu: ${input.tapu_durumu || "-"}`,
    `Kredi: ${input.krediye_uygunluk === 2 ? "Uygun" : "Diğer"}`,
  ];

  document.getElementById("property-tags").innerHTML = tags
    .map((tag) => `<span>${tag}</span>`)
    .join("");

  document.getElementById("quick-sale-price").textContent = formatPrice(
    analysis.quickSalePrice,
  );

  document.getElementById("balanced-sale-price").textContent = formatPrice(
    analysis.balancedSalePrice,
  );

  document.getElementById("high-sale-price").textContent = formatPrice(
    analysis.highSalePrice,
  );

  document.getElementById("six-month-price").textContent = formatPrice(
    analysis.sixMonthPrice,
  );

  document.getElementById("similar-count").textContent = analysis.similarCount;

  document.getElementById("market-average").textContent = formatPrice(
    analysis.avgPrice,
  );

  document.getElementById("market-median").textContent = formatPrice(
    analysis.medianPrice,
  );

  document.getElementById("market-m2-average").textContent = formatPrice(
    analysis.avgM2Price,
  );

  document.getElementById("analysis-report").textContent =
    buildAnalysisReport();
  document.getElementById("listing-copy").textContent = buildListingCopy();

  renderSimilarListings();
}

function renderSimilarListings() {
  const wrapper = document.getElementById("similar-listings");
  const listings = sellerState.similarListings;

  if (!listings.length) {
    wrapper.innerHTML = `<div class="listing-card">Benzer ilan bulunamadı.</div>`;
    return;
  }

  const sortedListings = [...listings].sort(
    (a, b) => getListingPrice(a) - getListingPrice(b),
  );

  wrapper.innerHTML = sortedListings
    .slice(0, 8)
    .map((item) => {
      const price = getListingPrice(item);
      const netM2 = getNetM2(item);
      const m2Price = netM2 ? price / netM2 : 0;

      return `
        <div class="listing-card">
          <strong>${item.title || "Benzer ilan"}</strong>
          <span>${item.district || "-"} / ${item.neighborhood || "-"}</span>
          <span>${item.oda || "-"}+${item.salon || "-"} | ${netM2 || "-"} m²</span>
          <span>m² fiyatı: ${formatPrice(m2Price)}</span>
          <b>${formatPrice(price)}</b>
        </div>
      `;
    })
    .join("");
}

function buildAnalysisReport() {
  const input = sellerState.modelInput;
  const analysis = sellerState.analysis;

  const adjustmentText = analysis.adjustmentNotes.length
    ? analysis.adjustmentNotes.map((note) => `- ${note}`).join("\n")
    : "- Özel düzeltme uygulanmadı.";

  return (
    `${input.ilce} / ${input.mahalle} bölgesinde eviniz için satış analizi hazırlandı.\n\n` +
    `Bu analizde kullanılan karşılaştırma seviyesi: ${analysis.matchLevel}.\n` +
    `Benzer ilan sayısı: ${analysis.similarCount}.\n` +
    `Tahmin güven seviyesi: ${analysis.confidence}.\n\n` +
    `Evinizin hesaplanan yaklaşık piyasa değeri ${formatPrice(analysis.estimatedPrice)} olarak görünüyor.\n\n` +
    `Satış stratejisi:\n` +
    `- Hızlı satmak isterseniz: ${formatPrice(analysis.quickSalePrice)} civarı daha agresif bir fiyat olur.\n` +
    `- Normal satış için: ${formatPrice(analysis.balancedSalePrice)} bandı dengeli görünür.\n` +
    `- Pazarlık payı bırakmak isterseniz: ${formatPrice(analysis.highSalePrice)} civarı denenebilir.\n` +
    `- 6 ay sonrası basit tahmini değer: ${formatPrice(analysis.sixMonthPrice)}.\n\n` +
    `Özellik bazlı düzeltmeler:\n${adjustmentText}`
  );
}

function buildListingCopy() {
  const input = sellerState.modelInput;
  const analysis = sellerState.analysis;

  return (
    `Başlık Önerileri:\n` +
    `1. ${input.mahalle} Bölgesinde ${input.oda}+${input.salon} Satılık Daire\n` +
    `2. ${input.ilce}'de ${input.net_metrekare} m² Net Kullanımlı Satılık Daire\n` +
    `3. ${input.mahalle}'nde Merkezi Konumda Satılık ${input.oda}+${input.salon} Daire\n\n` +
    `İlan Açıklaması:\n` +
    `${input.ilce} ${input.mahalle} bölgesinde yer alan bu ${input.oda}+${input.salon} daire, ` +
    `${input.net_metrekare} m² net ve ${input.brut_metrekare} m² brüt kullanım alanı sunmaktadır. ` +
    `${input.binanin_yasi} yaş aralığındaki binada bulunan daire, ${input.isitma_tipi || "belirtilen ısıtma tipi"} ile ısınmaktadır. ` +
    `Bölgedeki benzer ilanlar ve piyasa analizi dikkate alındığında, bu ev için dengeli ilan fiyatı yaklaşık ${formatPrice(analysis.balancedSalePrice)} olarak önerilmektedir. ` +
    `Hızlı satış hedeflenirse ${formatPrice(analysis.quickSalePrice)} bandı, pazarlık payı bırakılmak istenirse ${formatPrice(analysis.highSalePrice)} bandı değerlendirilebilir.`
  );
}

function addUserMessage(message) {
  const messages = document.getElementById("seller-chat-messages");

  const div = document.createElement("div");
  div.className = "chat-message user-message";
  div.textContent = message;

  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function addBotMessage(message) {
  const messages = document.getElementById("seller-chat-messages");

  const div = document.createElement("div");
  div.className = "chat-message bot-message";
  div.innerHTML = message;

  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

/*
  Eski JS chatbot mantığı kaldırıldı.
  Artık HouseAI Seller cevabı Python tarafındaki /api/seller-chatbot endpoint'inden geliyor.
*/
async function sendSellerChatToPython(message) {
  try {
    const response = await fetch("/api/seller-chatbot", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: message,
        modelInput: sellerState.modelInput,
        predictionResult: sellerState.predictionResult,
        analysis: sellerState.analysis,
      }),
    });

    if (!response.ok) {
      throw new Error("seller-chatbot endpoint hata verdi.");
    }

    const result = await response.json();

    if (result.reply) {
      addBotMessage(result.reply);
    } else {
      addBotMessage("Python chatbot cevap döndürmedi.");
    }
  } catch (error) {
    console.error(error);

    addBotMessage(
      "Python tarafındaki HouseAI Seller chatbot çalışmadı. app.py içinde /api/seller-chatbot endpoint'ini ve seller_ai_service.py dosyasını kontrol et.",
    );
  }
}

async function initSellerPage() {
  const storageData = readStorageData();

  sellerState.modelInput = storageData.modelInput;
  sellerState.predictionResult = storageData.predictionResult;

  if (!sellerState.modelInput) {
    renderPage();
    return;
  }

  const listings = await loadListings();
  const similarResult = findSimilarListings(sellerState.modelInput, listings);

  sellerState.similarListings = similarResult.listings;

  sellerState.analysis = calculateAnalysis(
    sellerState.modelInput,
    sellerState.predictionResult,
    similarResult,
  );

  renderPage();

  if (sellerState.analysis) {
    setTimeout(() => {
      addBotMessage(
        `Analizi hazırladım ✅<br><br>` +
          `Evin tahmini piyasa değeri: <strong>${formatPrice(sellerState.analysis.estimatedPrice)}</strong><br>` +
          `Dengeli satış fiyatı: <strong>${formatPrice(sellerState.analysis.balancedSalePrice)}</strong><br><br>` +
          `Satış hedefini yazarsan Python tarafındaki HouseAI Seller stratejiyi ona göre yorumlayacak.`,
      );
    }, 600);
  }
}

document
  .getElementById("seller-chat-form")
  .addEventListener("submit", function (event) {
    event.preventDefault();

    const input = document.getElementById("seller-chat-input");
    const message = input.value.trim();

    if (!message) return;

    addUserMessage(message);
    input.value = "";

    sendSellerChatToPython(message);
  });

const sellerChatPanel = document.getElementById("seller-chat-panel");
const sellerLauncher = document.getElementById("sellerai-launcher");
const sellerCloseBtn = document.getElementById("seller-chat-close-btn");
const sellerChatInput = document.getElementById("seller-chat-input");

function openSellerChat() {
  sellerChatPanel.classList.remove("hidden");
  sellerLauncher.style.display = "none";

  setTimeout(() => {
    if (sellerChatInput) sellerChatInput.focus();
  }, 150);
}

function closeSellerChat() {
  sellerChatPanel.classList.add("hidden");
  sellerLauncher.style.display = "flex";
}

if (sellerLauncher) {
  sellerLauncher.addEventListener("click", openSellerChat);
}

if (sellerCloseBtn) {
  sellerCloseBtn.addEventListener("click", closeSellerChat);
}

initSellerPage();
