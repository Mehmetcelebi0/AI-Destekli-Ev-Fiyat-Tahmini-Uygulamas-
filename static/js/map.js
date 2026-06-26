const map = L.map("map").setView([41.0082, 28.9784], 10);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "© OpenStreetMap",
}).addTo(map);

let districtCenters = [];
let allListings = [];
let visibleListings = [];

let isSelectingLocation = false;
let userHomeMarker = null;

let priceTrendChart = null;
let neighborhoodPriceChart = null;

let chatbotState = {};

const clusterGroup = L.markerClusterGroup({
  chunkedLoading: true,
  maxClusterRadius: 55,
  spiderfyOnMaxZoom: true,
  showCoverageOnHover: false,
});

map.addLayer(clusterGroup);

Promise.all([
  fetch("district_centers.json").then((response) => {
    if (!response.ok) throw new Error("district_centers.json yüklenemedi.");
    return response.json();
  }),

  fetch("listings.json").then((response) => {
    if (!response.ok) throw new Error("listings.json yüklenemedi.");
    return response.json();
  }),
])
  .then(([districtData, listingData]) => {
    districtCenters = districtData.map((item) => ({
      district: item.district,
      neighborhood: item.neighborhood,
      lat: Number(item.lat),
      lng: Number(item.lng),
    }));

    allListings = listingData.map((item) => ({
      id: Number(item.id),
      title: item.title || "İlan",
      district: item.district,
      neighborhood: item.neighborhood,
      price: Number(item.price),
      predictedPrice: Number(item.predictedPrice || item.predicted_price || 0),
      lat: Number(item.lat),
      lng: Number(item.lng),
      status: item.status || "normal",
      net_metrekare: Number(item.net_metrekare),
      brut_metrekare: Number(item.brut_metrekare),
      oda: Number(item.oda),
      salon: Number(item.salon),
      binanin_yasi: item.binanin_yasi || "-",
      banyo_sayisi: Number(item.banyo_sayisi),
    }));

    visibleListings = getRandomListings(allListings, 500);

    renderListings(visibleListings);
    renderEmptyDashboard();
    restoreSelectedLocationContext();
  })
  .catch((error) => {
    console.error(error);
    alert("JSON dosyaları yüklenemedi. Local server ile çalıştır.");
  });

function formatPrice(price) {
  return Number(price || 0).toLocaleString("tr-TR") + " TL";
}

function shortPrice(price) {
  const value = Number(price || 0);

  if (value >= 1000000) {
    return "₺" + (value / 1000000).toFixed(1).replace(".", ",") + "M";
  }

  return "₺" + Math.round(value / 1000) + "K";
}

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

function getRandomListings(source, count) {
  const copied = [...source];

  for (let i = copied.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copied[i], copied[j]] = [copied[j], copied[i]];
  }

  return copied.slice(0, count);
}

function getMarkerColor(status) {
  if (status === "expensive") return "#ff1f1f";
  if (status === "opportunity") return "#16a34a";
  return "#2d5bff";
}

function getStatusText(status) {
  if (status === "expensive") return "Pahalı / Anomali";
  if (status === "opportunity") return "Fırsat İlanı";
  return "Normal İlan";
}

function getStatusClass(status) {
  if (status === "expensive") return "status-expensive";
  if (status === "opportunity") return "status-opportunity";
  return "status-normal";
}

function getItemPriceText(item) {
  return item.price_text || formatPrice(item.price);
}

function getItemPredictedPriceText(item) {
  return (
    item.predicted_price_text ||
    item.predictedPriceText ||
    formatPrice(item.predictedPrice || item.predicted_price || 0)
  );
}

function createListingPopupContent(item) {
  return `
    <div class="custom-popup">
      <h3>${item.title || "İlan"}</h3>
      <p><strong>İlçe:</strong> ${item.district || "-"}</p>
      <p><strong>Mahalle:</strong> ${item.neighborhood || "-"}</p>
      <p><strong>Net m²:</strong> ${item.net_metrekare || "-"}</p>
      <p><strong>Brüt m²:</strong> ${item.brut_metrekare || "-"}</p>
      <p><strong>Oda:</strong> ${item.oda || "-"}+${item.salon ?? "-"}</p>
      <p><strong>Bina Yaşı:</strong> ${item.binanin_yasi || "-"}</p>
      <p><strong>Banyo:</strong> ${item.banyo_sayisi ?? "-"}</p>
      <p class="price">${getItemPriceText(item)}</p>
      <p><strong>Tahmini Fiyat:</strong> ${getItemPredictedPriceText(item)}</p>
      <span class="status-badge ${getStatusClass(item.status)}">
        ${getStatusText(item.status)}
      </span>
    </div>
  `;
}

function renderListings(listingArray) {
  clusterGroup.clearLayers();

  listingArray.forEach((item) => {
    if (!item.lat || !item.lng) return;

    const marker = L.circleMarker([Number(item.lat), Number(item.lng)], {
      radius: 8,
      color: "white",
      weight: 2,
      fillColor: getMarkerColor(item.status),
      fillOpacity: 0.95,
    });

    marker.bindTooltip(shortPrice(item.price), {
      permanent: true,
      direction: "top",
      offset: [0, -8],
      className: "price-label",
    });

    marker.bindPopup(createListingPopupContent(item));

    clusterGroup.addLayer(marker);
  });

  if (listingArray.length > 0) {
    const validCoords = listingArray
      .filter((item) => item.lat && item.lng)
      .map((item) => [Number(item.lat), Number(item.lng)]);

    if (validCoords.length > 0) {
      const bounds = L.latLngBounds(validCoords);

      map.fitBounds(bounds, {
        padding: [70, 70],
      });
    }
  }
}

const selectLocationBtn = document.getElementById("select-location-btn");

if (selectLocationBtn) {
  selectLocationBtn.addEventListener("click", function () {
    isSelectingLocation = true;

    document.getElementById("selected-location-text").textContent =
      "Haritada evinizin olduğu noktaya tıklayın.";
  });
}

map.on("click", function (event) {
  if (!isSelectingLocation) return;

  if (districtCenters.length === 0 || allListings.length === 0) {
    alert("Veriler henüz yüklenmedi.");
    return;
  }

  const lat = event.latlng.lat;
  const lng = event.latlng.lng;

  if (userHomeMarker !== null) {
    map.removeLayer(userHomeMarker);
  }

  const homeIcon = L.divIcon({
    className: "",
    html: '<div class="home-marker"></div>',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });

  userHomeMarker = L.marker([lat, lng], {
    icon: homeIcon,
  }).addTo(map);

  const nearestArea = findNearestNeighborhood(lat, lng);

  const selectedLocationData = {
    lat,
    lng,
    district: nearestArea.district,
    neighborhood: nearestArea.neighborhood,
  };

  localStorage.setItem(
    "selectedHomeLocation",
    JSON.stringify(selectedLocationData),
  );

  chatbotState = {
    ...chatbotState,
    mode: "area_context",
    lastDistrict: nearestArea.district,
    lastNeighborhood: nearestArea.neighborhood,
    selectedLat: lat,
    selectedLng: lng,
  };

  document.getElementById("selected-location-text").innerHTML = `
    Seçilen konum: ${lat.toFixed(5)}, ${lng.toFixed(5)}<br>
    Tahmini bölge: <strong>${nearestArea.district} / ${nearestArea.neighborhood}</strong>
  `;

  filterListingsByDistrict(nearestArea.district, nearestArea.neighborhood);

  addBotMessage(
    `Konum seçildi: ${nearestArea.district} / ${nearestArea.neighborhood}. Haritada sadece bu mahalledeki ilanlar gösteriliyor.`,
  );

  isSelectingLocation = false;
});

function restoreSelectedLocationContext() {
  const savedLocation = localStorage.getItem("selectedHomeLocation");

  if (!savedLocation) return;

  try {
    const parsed = JSON.parse(savedLocation);

    if (!parsed || !parsed.district || !parsed.neighborhood) return;

    chatbotState = {
      ...chatbotState,
      mode: "area_context",
      lastDistrict: parsed.district,
      lastNeighborhood: parsed.neighborhood,
      selectedLat: parsed.lat || null,
      selectedLng: parsed.lng || null,
    };
  } catch (error) {
    console.warn("selectedHomeLocation okunamadı:", error);
  }
}

function findNearestNeighborhood(lat, lng) {
  let nearest = null;
  let minDistance = Infinity;

  districtCenters.forEach((center) => {
    const distance = calculateDistanceKm(lat, lng, center.lat, center.lng);

    if (distance < minDistance) {
      minDistance = distance;
      nearest = center;
    }
  });

  return nearest;
}

function filterListingsByDistrict(districtName, neighborhoodName = "") {
  const selectedDistrict = normalizeText(districtName);
  const selectedNeighborhood = normalizeNeighborhood(neighborhoodName);

  const filteredListings = allListings.filter((item) => {
    const itemDistrict = normalizeText(item.district);
    const itemNeighborhood = normalizeNeighborhood(item.neighborhood);

    const districtMatches = itemDistrict === selectedDistrict;

    const neighborhoodMatches =
      selectedNeighborhood === "" || itemNeighborhood === selectedNeighborhood;

    return districtMatches && neighborhoodMatches;
  });

  visibleListings = filteredListings;

  renderListings(visibleListings);
  showDistrictAnalysisResult(districtName, neighborhoodName, visibleListings);
}

function getAverageM2Price(listings) {
  const valid = listings.filter((item) => {
    return Number(item.net_metrekare) > 0 && Number(item.price) > 0;
  });

  if (valid.length === 0) return 0;

  const total = valid.reduce((sum, item) => {
    return sum + Number(item.price) / Number(item.net_metrekare);
  }, 0);

  return Math.round(total / valid.length);
}

function getNeighborhoodAverageData(listings) {
  const neighborhoodData = {};

  listings.forEach((item) => {
    const neighborhood = item.neighborhood || "Bilinmeyen";

    if (!neighborhoodData[neighborhood]) {
      neighborhoodData[neighborhood] = {
        totalPrice: 0,
        totalM2Price: 0,
        m2Count: 0,
        count: 0,
      };
    }

    neighborhoodData[neighborhood].totalPrice += Number(item.price || 0);

    if (Number(item.net_metrekare) > 0 && Number(item.price) > 0) {
      neighborhoodData[neighborhood].totalM2Price +=
        Number(item.price) / Number(item.net_metrekare);

      neighborhoodData[neighborhood].m2Count += 1;
    }

    neighborhoodData[neighborhood].count += 1;
  });

  return Object.keys(neighborhoodData)
    .map((neighborhood) => {
      const data = neighborhoodData[neighborhood];

      return {
        neighborhood,
        avgPrice: Math.round(data.totalPrice / data.count),
        avgM2Price:
          data.m2Count > 0 ? Math.round(data.totalM2Price / data.m2Count) : 0,
        count: data.count,
      };
    })
    .sort((a, b) => b.avgPrice - a.avgPrice);
}

function createFakeTrend(basePrice) {
  const labels = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];

  const values = labels.map((_, index) => {
    const change = 0.86 + index * 0.025 + Math.sin(index) * 0.035;
    return Math.round(basePrice * change);
  });

  return {
    labels,
    values,
  };
}

function renderEmptyDashboard() {
  if (priceTrendChart) priceTrendChart.destroy();
  if (neighborhoodPriceChart) neighborhoodPriceChart.destroy();

  priceTrendChart = new Chart(document.getElementById("priceTrendChart"), {
    type: "line",
    data: {
      labels: [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
      ],
      datasets: [
        {
          data: [20, 23, 24, 22, 28, 32, 31, 34, 35, 39, 37, 42],
          borderColor: "#2D5BFF",
          backgroundColor: "rgba(32, 214, 255, 0.24)",
          pointBackgroundColor: "#2D5BFF",
          fill: true,
          tension: 0.45,
        },
      ],
    },
    options: getLineOptions(),
  });

  neighborhoodPriceChart = new Chart(
    document.getElementById("neighborhoodPriceChart"),
    {
      type: "bar",
      data: {
        labels: ["Mahalle 1", "Mahalle 2", "Mahalle 3"],
        datasets: [
          {
            data: [10, 7, 5],
            backgroundColor: "#20d6ff",
            borderRadius: 8,
          },
        ],
      },
      options: getBarOptions(),
    },
  );
}

function showDistrictAnalysisResult(
  selectedDistrict,
  selectedNeighborhood,
  districtListings,
) {
  const resultEl = document.getElementById("analysis-result");
  const areaTitle = document.getElementById("selected-area-title");
  const avgM2PriceEl = document.getElementById("avg-m2-price");

  areaTitle.textContent = selectedNeighborhood
    ? `${selectedDistrict}, ${selectedNeighborhood}`
    : selectedDistrict || "Henüz bölge seçilmedi";

  if (!districtListings || districtListings.length === 0) {
    resultEl.innerHTML = selectedNeighborhood
      ? `<strong>${selectedDistrict} / ${selectedNeighborhood}</strong> için uygun ilan bulunamadı.`
      : "Bu bölgede ilan bulunamadı.";

    avgM2PriceEl.textContent = "₺0";

    renderEmptyDashboard();
    return;
  }

  const avgM2Price = getAverageM2Price(districtListings);

  const neighborhoodList = getNeighborhoodAverageData(districtListings).slice(
    0,
    6,
  );

  avgM2PriceEl.textContent = "₺" + avgM2Price.toLocaleString("tr-TR");

  const trend = createFakeTrend(avgM2Price);

  resultEl.innerHTML = `
    <strong>${selectedDistrict}</strong> ${
      selectedNeighborhood ? `/ <strong>${selectedNeighborhood}</strong>` : ""
    } analiz edildi.<br>
    <strong>Toplam ilan:</strong> ${districtListings.length}<br>
    <strong>En pahalı mahalle:</strong> ${
      neighborhoodList[0]?.neighborhood || "-"
    } - ${formatPrice(neighborhoodList[0]?.avgPrice || 0)}<br>
    <strong>Ortalama m² fiyatı:</strong> ₺${avgM2Price.toLocaleString("tr-TR")}
  `;

  if (priceTrendChart) priceTrendChart.destroy();
  if (neighborhoodPriceChart) neighborhoodPriceChart.destroy();

  priceTrendChart = new Chart(document.getElementById("priceTrendChart"), {
    type: "line",
    data: {
      labels: trend.labels,
      datasets: [
        {
          label: "₺ / m²",
          data: trend.values,
          borderColor: "#2D5BFF",
          backgroundColor: "rgba(32, 214, 255, 0.24)",
          pointBackgroundColor: "#2D5BFF",
          pointRadius: 3,
          borderWidth: 3,
          fill: true,
          tension: 0.45,
        },
      ],
    },
    options: getLineOptions(),
  });

  neighborhoodPriceChart = new Chart(
    document.getElementById("neighborhoodPriceChart"),
    {
      type: "bar",
      data: {
        labels: neighborhoodList.map((item) => item.neighborhood),
        datasets: [
          {
            label: "Ortalama Fiyat",
            data: neighborhoodList.map((item) => item.avgPrice),
            backgroundColor: "#20d6ff",
            borderRadius: 8,
          },
        ],
      },
      options: getBarOptions(),
    },
  );
}

function getLineOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        callbacks: {
          label: function (context) {
            return "₺" + Number(context.raw).toLocaleString("tr-TR") + " / m²";
          },
        },
      },
    },
    scales: {
      x: {
        grid: {
          display: false,
        },
      },
      y: {
        ticks: {
          callback: function (value) {
            return "₺" + Number(value).toLocaleString("tr-TR");
          },
        },
      },
    },
  };
}

function getBarOptions() {
  return {
    indexAxis: "y",
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        callbacks: {
          label: function (context) {
            return " Ortalama: " + formatPrice(context.raw);
          },
        },
      },
    },
    scales: {
      x: {
        ticks: {
          callback: function (value) {
            return shortPrice(value);
          },
        },
      },
    },
  };
}

const resizeHandle = document.getElementById("resize-handle");
const sidebar = document.querySelector(".sidebar");

let isResizing = false;

if (resizeHandle && sidebar) {
  resizeHandle.addEventListener("mousedown", function () {
    isResizing = true;
    document.body.style.cursor = "col-resize";
  });

  document.addEventListener("mousemove", function (event) {
    if (!isResizing) return;

    const newWidth = event.clientX;
    const minWidth = 460;
    const maxWidth = window.innerWidth * 0.7;

    if (newWidth >= minWidth && newWidth <= maxWidth) {
      sidebar.style.width = newWidth + "px";
      map.invalidateSize();
    }
  });

  document.addEventListener("mouseup", function () {
    isResizing = false;
    document.body.style.cursor = "default";
  });
}

function getCurrentLocationContext() {
  const savedLocation = localStorage.getItem("selectedHomeLocation");

  if (!savedLocation) {
    return {};
  }

  try {
    const parsed = JSON.parse(savedLocation);

    return {
      district: parsed.district || "",
      neighborhood: parsed.neighborhood || "",
      lat: parsed.lat || null,
      lng: parsed.lng || null,
    };
  } catch (error) {
    return {};
  }
}

async function sendMessageToPythonBot(message) {
  try {
    const response = await fetch("/api/map-chatbot", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: message,
        state: chatbotState,
        context: getCurrentLocationContext(),
      }),
    });

    if (!response.ok) {
      throw new Error("map-chatbot endpoint hata verdi.");
    }

    const result = await response.json();

    chatbotState = result.state || chatbotState || {};

    addBotMessage(result.reply);

    if (result.action === "fly_to_area_and_select") {
      const data = result.data;

      map.setView([data.lat, data.lng], data.zoom || 16);

      isSelectingLocation = true;

      document.getElementById("selected-location-text").textContent =
        "HouseAI seni mahalleye götürdü. Şimdi haritada evinin tam konumuna tıkla.";
    }

    if (result.action === "show_market_result") {
      const data = result.data;

      if (data.center && data.center.lat && data.center.lng) {
        map.setView([data.center.lat, data.center.lng], data.center.zoom || 15);
      }

      if (data.examples && data.examples.length > 0) {
        showChatbotExamples(data.examples);
        renderListings(data.examples);
        showDistrictAnalysisResult(
          data.district,
          data.neighborhood || "",
          data.examples,
        );
      } else {
        renderListings([]);
        showDistrictAnalysisResult(data.district, data.neighborhood || "", []);
      }
    }
  } catch (error) {
    console.error(error);

    addBotMessage(
      "Python tarafındaki HouseAI Map Chatbot çalışmıyor olabilir. app.py içinde /api/map-chatbot endpoint'ini kontrol et.",
    );
  }
}

function addUserMessage(message) {
  const messagesEl = document.getElementById("chatbot-messages");

  if (!messagesEl) return;

  const div = document.createElement("div");
  div.className = "chat-message user-message";
  div.textContent = message;

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addBotMessage(message) {
  const messagesEl = document.getElementById("chatbot-messages");

  if (!messagesEl) return;

  const div = document.createElement("div");
  div.className = "chat-message bot-message";
  div.innerHTML = message;

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showChatbotExamples(examples) {
  const messagesEl = document.getElementById("chatbot-messages");

  if (!messagesEl) return;

  const wrapper = document.createElement("div");
  wrapper.className = "chat-examples";

  examples.forEach((item) => {
    const netM2 = Number(item.net_metrekare || 0);
    const brutM2 = Number(item.brut_metrekare || 0);
    const oda = Number(item.oda || 0);
    const salon = Number(item.salon || 0);
    const banyo = Number(item.banyo_sayisi || 0);
    const binaYasi = item.binanin_yasi || "-";

    const card = document.createElement("div");
    card.className = "chat-listing-card";

    card.innerHTML = `
      <strong>${item.title || "İlan"}</strong>
      <span><b>Konum:</b> ${item.district || "-"} / ${
        item.neighborhood || "-"
      }</span>
      <span><b>Oda:</b> ${oda}+${salon}</span>
      <span><b>Net m²:</b> ${netM2 || "-"}</span>
      <span><b>Brüt m²:</b> ${brutM2 || "-"}</span>
      <span><b>Bina Yaşı:</b> ${binaYasi}</span>
      <span><b>Banyo:</b> ${banyo || "-"}</span>
      <b>${getItemPriceText(item)}</b>
      <button type="button">Haritada Göster</button>
    `;

    const button = card.querySelector("button");

    button.addEventListener("click", function () {
      map.setView([item.lat, item.lng], 17);

      L.popup()
        .setLatLng([item.lat, item.lng])
        .setContent(createListingPopupContent(item))
        .openOn(map);
    });

    wrapper.appendChild(card);
  });

  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

const chatbotForm = document.getElementById("chatbot-form");
const chatbotInput = document.getElementById("chatbot-input");
const chatbotWidget = document.getElementById("chatbot-widget");
const chatbotLauncher = document.getElementById("houseai-launcher");
const chatbotCloseBtn = document.getElementById("chatbot-close-btn");

function openChatbot() {
  if (!chatbotWidget || !chatbotLauncher) return;

  chatbotWidget.classList.remove("hidden");
  chatbotLauncher.style.display = "none";

  setTimeout(() => {
    if (chatbotInput) chatbotInput.focus();
  }, 150);
}

function closeChatbot() {
  if (!chatbotWidget || !chatbotLauncher) return;

  chatbotWidget.classList.add("hidden");
  chatbotLauncher.style.display = "flex";
}

if (chatbotLauncher) {
  chatbotLauncher.addEventListener("click", openChatbot);
}

if (chatbotCloseBtn) {
  chatbotCloseBtn.addEventListener("click", closeChatbot);
}

if (chatbotForm) {
  chatbotForm.addEventListener("submit", function (event) {
    event.preventDefault();

    const message = chatbotInput.value.trim();

    if (!message) return;

    addUserMessage(message);
    chatbotInput.value = "";

    sendMessageToPythonBot(message);
  });
}
// ======================================================
// ANA SAYFA AUTH DURUMU
// Giriş yapan kullanıcı varsa sağ üstte kullanıcı bilgisi gösterir.
// Çıkış yapınca eski Giriş Yap / Üye Ol / Admin butonlarına döner.
// ======================================================

// ======================================================
// ANA SAYFA AUTH DURUMU
// User giriş yaptıysa user bilgisi,
// Admin giriş yaptıysa admin bilgisi gösterir.
// ======================================================

async function loadHomeAuthState() {
  const guestActions = document.getElementById("guest-actions");

  const userActions = document.getElementById("user-actions");
  const welcomeText = document.getElementById("top-user-welcome");
  const emailText = document.getElementById("top-user-email");
  const avatar = document.getElementById("top-user-avatar");
  const logoutBtn = document.getElementById("top-logout-btn");

  const adminActions = document.getElementById("admin-actions");
  const adminWelcomeText = document.getElementById("top-admin-welcome");
  const adminEmailText = document.getElementById("top-admin-email");
  const adminAvatar = document.getElementById("top-admin-avatar");
  const adminLogoutBtn = document.getElementById("top-admin-logout-btn");

  if (!guestActions) return;

  function showGuest() {
    guestActions.classList.remove("hidden");

    if (userActions) {
      userActions.classList.add("hidden");
    }

    if (adminActions) {
      adminActions.classList.add("hidden");
    }
  }

  function showUser(user) {
    guestActions.classList.add("hidden");

    if (adminActions) {
      adminActions.classList.add("hidden");
    }

    if (userActions) {
      userActions.classList.remove("hidden");
    }

    const name = (user.name || "").trim();
    const email = (user.email || "").trim();

    let displayName = name;

    if (!displayName && email) {
      displayName = email.split("@")[0];
    }

    if (!displayName) {
      displayName = "Kullanıcı";
    }

    if (welcomeText) {
      welcomeText.textContent = `Hoş geldiniz, ${displayName} Bey`;
    }

    if (emailText) {
      emailText.textContent = email || "-";
    }

    if (avatar) {
      avatar.textContent = displayName.charAt(0).toUpperCase();
    }
  }

  function showAdmin(admin) {
    guestActions.classList.add("hidden");

    if (userActions) {
      userActions.classList.add("hidden");
    }

    if (adminActions) {
      adminActions.classList.remove("hidden");
    }

    const name = (admin.name || "Admin").trim();
    const email = (admin.email || "").trim();

    if (adminWelcomeText) {
      adminWelcomeText.textContent = `Hoş geldiniz, ${name}`;
    }

    if (adminEmailText) {
      adminEmailText.textContent = email || "-";
    }

    if (adminAvatar) {
      adminAvatar.textContent = name.charAt(0).toUpperCase();
    }
  }

  // 1) Önce admin kontrolü yap.
  // Admin panelden "Siteyi Aç" denince ana sayfada admin görünmeli.
  try {
    const adminResponse = await fetch("/api/admin/me", {
      method: "GET",
      credentials: "same-origin",
    });

    if (adminResponse.ok) {
      const adminData = await adminResponse.json();

      if (adminData.success && adminData.user) {
        showAdmin(adminData.user);

        if (adminLogoutBtn) {
          adminLogoutBtn.onclick = async () => {
            try {
              await fetch("/api/admin/logout", {
                method: "POST",
                credentials: "same-origin",
              });
            } catch (error) {
              console.error("Admin çıkış yapılırken hata oluştu:", error);
            }

            showGuest();
            window.location.href = "/";
          };
        }

        return;
      }
    }
  } catch (error) {
    console.warn("Admin oturum kontrolü yapılamadı:", error);
  }

  // 2) Admin yoksa normal user kontrolü yap.
  try {
    const userResponse = await fetch("/api/user/me", {
      method: "GET",
      credentials: "same-origin",
    });

    if (!userResponse.ok) {
      showGuest();
      return;
    }

    const userData = await userResponse.json();

    if (!userData.success || !userData.user) {
      showGuest();
      return;
    }

    showUser(userData.user);

    if (logoutBtn) {
      logoutBtn.onclick = async () => {
        try {
          await fetch("/api/user/logout", {
            method: "POST",
            credentials: "same-origin",
          });
        } catch (error) {
          console.error("Kullanıcı çıkış yapılırken hata oluştu:", error);
        }

        showGuest();
        window.location.href = "/";
      };
    }
  } catch (error) {
    showGuest();
  }
}

document.addEventListener("DOMContentLoaded", loadHomeAuthState);
