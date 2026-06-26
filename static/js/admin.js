const navButtons = document.querySelectorAll(".nav-btn");

const sections = {
  dashboard: document.getElementById("dashboardSection"),
  data: document.getElementById("dataSection"),
  listings: document.getElementById("listingsSection"),
  users: document.getElementById("usersSection"),
  activities: document.getElementById("activitiesSection"),
};

const logoutBtn = document.getElementById("logoutBtn");

const adminName = document.getElementById("adminName");
const adminEmail = document.getElementById("adminEmail");

const totalListings = document.getElementById("totalListings");
const emlakjetListings = document.getElementById("emlakjetListings");
const totalUsers = document.getElementById("totalUsers");
const lastAddedCount = document.getElementById("lastAddedCount");

const lastRunAt = document.getElementById("lastRunAt");
const linksFound = document.getElementById("linksFound");
const linksProcessed = document.getElementById("linksProcessed");
const addedCount = document.getElementById("addedCount");
const skippedCount = document.getElementById("skippedCount");
const rejectedCount = document.getElementById("rejectedCount");

const runImportBtn = document.getElementById("runImportBtn");
const runImportBtn2 = document.getElementById("runImportBtn2");
const importStatusBox = document.getElementById("importStatusBox");

const dataStatusText = document.getElementById("dataStatusText");
const dataStatusMessage = document.getElementById("dataStatusMessage");
const statusStartedAt = document.getElementById("statusStartedAt");
const statusFinishedAt = document.getElementById("statusFinishedAt");
const statusLogFile = document.getElementById("statusLogFile");

const refreshStatsBtn = document.getElementById("refreshStatsBtn");
const refreshListingsBtn = document.getElementById("refreshListingsBtn");
const refreshUsersBtn = document.getElementById("refreshUsersBtn");

const latestListingsTable = document.getElementById("latestListingsTable");
const usersTable = document.getElementById("usersTable");
const listingSearch = document.getElementById("listingSearch");

const adminCount = document.getElementById("adminCount");
const normalUserCount = document.getElementById("normalUserCount");
const todayUsers = document.getElementById("todayUsers");

const pricePredictionCount = document.getElementById("pricePredictionCount");
const sellerAnalysisCount = document.getElementById("sellerAnalysisCount");
const refreshActivitiesBtn = document.getElementById("refreshActivitiesBtn");
const activitiesTable = document.getElementById("activitiesTable");

let statusPoller = null;
let latestListings = [];

function formatPrice(value) {
  const number = Number(value || 0);

  if (!Number.isFinite(number)) {
    return "0 TL";
  }

  return Math.round(number).toLocaleString("tr-TR") + " TL";
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, options);

  if (response.status === 401) {
    window.location.href = "/admin-login";
    return null;
  }

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.message || "İstek başarısız.");
  }

  return data;
}

function setActiveSection(sectionName) {
  navButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.section === sectionName);
  });

  Object.entries(sections).forEach(([name, section]) => {
    if (!section) return;
    section.classList.toggle("active", name === sectionName);
  });
}

navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveSection(button.dataset.section);
  });
});

async function loadMe() {
  const data = await fetchJSON("/api/admin/me");

  if (!data || !data.user) {
    window.location.href = "/admin-login";
    return;
  }

  adminName.textContent = data.user.name || "Admin";
  adminEmail.textContent = data.user.email || "";
}

async function loadStats() {
  const data = await fetchJSON("/api/admin/stats");

  if (!data) return;

  const stats = data.stats || {};
  const lastRun = stats.last_run || {};
  const activitySummary = stats.activity_summary || {};

  totalListings.textContent = stats.total_listings ?? 0;
  emlakjetListings.textContent = stats.emlakjet_listings ?? 0;
  totalUsers.textContent = stats.total_users ?? 0;
  lastAddedCount.textContent = stats.last_added_count ?? 0;

  lastRunAt.textContent = lastRun.run_at || "-";
  linksFound.textContent = lastRun.links_found ?? 0;
  linksProcessed.textContent = lastRun.links_processed ?? 0;
  addedCount.textContent = lastRun.added_count ?? 0;
  skippedCount.textContent = lastRun.skipped_count ?? 0;
  rejectedCount.textContent = lastRun.rejected_count ?? 0;

  adminCount.textContent = stats.admin_count ?? 0;
  normalUserCount.textContent = stats.normal_user_count ?? 0;
  todayUsers.textContent = stats.today_users ?? 0;

  if (pricePredictionCount) {
    pricePredictionCount.textContent =
      activitySummary.price_prediction_count ?? 0;
  }

  if (sellerAnalysisCount) {
    sellerAnalysisCount.textContent =
      activitySummary.seller_analysis_count ?? 0;
  }

  renderImportStatus(stats.import_status || {});
}

function renderImportStatus(status) {
  const running = Boolean(status.running);

  if (running) {
    importStatusBox.textContent = "Veri çekme işlemi çalışıyor...";
    importStatusBox.style.background = "#fef3c7";
    importStatusBox.style.color = "#92400e";

    dataStatusText.textContent = "Çalışıyor";
  } else if (status.success === true) {
    importStatusBox.textContent = "Son veri çekme işlemi başarıyla tamamlandı.";
    importStatusBox.style.background = "#dcfce7";
    importStatusBox.style.color = "#166534";

    dataStatusText.textContent = "Tamamlandı";
  } else if (status.success === false) {
    importStatusBox.textContent = "Son veri çekme işlemi hata aldı.";
    importStatusBox.style.background = "#fee2e2";
    importStatusBox.style.color = "#991b1b";

    dataStatusText.textContent = "Hata";
  } else {
    importStatusBox.textContent = status.message || "Henüz işlem yok.";
    importStatusBox.style.background = "#eff6ff";
    importStatusBox.style.color = "#1e3a8a";

    dataStatusText.textContent = "Beklemede";
  }

  dataStatusMessage.textContent = status.message || "-";
  statusStartedAt.textContent = status.started_at || "-";
  statusFinishedAt.textContent = status.finished_at || "-";
  statusLogFile.textContent = status.log_file || "-";

  runImportBtn.disabled = running;
  runImportBtn2.disabled = running;
}

async function loadImportStatus() {
  const data = await fetchJSON("/api/admin/import-status");

  if (!data) return;

  renderImportStatus(data.status || {});

  if (!data.status?.running && statusPoller) {
    clearInterval(statusPoller);
    statusPoller = null;

    await loadStats();
    await loadLatestListings();
    await loadActivities();
  }
}

async function runImport() {
  const confirmed = confirm(
    "Son 24 saatlik Emlakjet verileri çekilecek. İşlem birkaç dakika sürebilir. Başlatılsın mı?",
  );

  if (!confirmed) return;

  runImportBtn.disabled = true;
  runImportBtn2.disabled = true;

  try {
    const data = await fetchJSON("/api/admin/run-import", {
      method: "POST",
    });

    if (!data) return;

    renderImportStatus(data.status || {});

    if (!statusPoller) {
      statusPoller = setInterval(loadImportStatus, 3000);
    }
  } catch (error) {
    alert(error.message || "Veri çekme işlemi başlatılamadı.");
    await loadImportStatus();
  }
}

function renderLatestListings(items) {
  latestListingsTable.innerHTML = "";

  if (!items.length) {
    latestListingsTable.innerHTML = `
      <tr>
        <td colspan="8">Gösterilecek ilan bulunamadı.</td>
      </tr>
    `;
    return;
  }

  const rows = items
    .map((item) => {
      const sourceLink = item.source_url
        ? `<a href="${item.source_url}" target="_blank">Aç</a>`
        : "-";

      return `
      <tr>
        <td>${item.id ?? "-"}</td>
        <td>${item.title ?? "-"}</td>
        <td>${item.district ?? "-"}</td>
        <td>${item.neighborhood ?? "-"}</td>
        <td>${item.oda ?? "-"}+${item.salon ?? "-"}</td>
        <td>${item.net_metrekare ?? "-"} m²</td>
        <td>${formatPrice(item.price)}</td>
        <td>${sourceLink}</td>
      </tr>
    `;
    })
    .join("");

  latestListingsTable.innerHTML = rows;
}

async function loadLatestListings() {
  const data = await fetchJSON("/api/admin/latest-imported-listings");

  if (!data) return;

  latestListings = data.items || [];
  renderLatestListings(latestListings);
}

async function loadUsers() {
  const data = await fetchJSON("/api/admin/users");

  if (!data) return;

  const users = data.users || [];

  if (!users.length) {
    usersTable.innerHTML = `
      <tr>
        <td colspan="6">Üye bulunamadı.</td>
      </tr>
    `;
    return;
  }

  usersTable.innerHTML = users
    .map((user) => {
      return `
      <tr>
        <td>${user.id ?? "-"}</td>
        <td>${user.name ?? "-"}</td>
        <td>${user.email ?? "-"}</td>
        <td>${user.role ?? "-"}</td>
        <td>${user.created_at ?? "-"}</td>
        <td>${user.last_login ?? "-"}</td>
      </tr>
    `;
    })
    .join("");
}

function activityTypeText(type) {
  const map = {
    register: "Kayıt",
    login: "Giriş",
    logout: "Çıkış",
    price_prediction: "Fiyat Tahmini",
    seller_analysis: "Satış Analizi",
    map_chat: "Harita Chatbot",
  };

  return map[type] || type || "-";
}

async function loadActivities() {
  const data = await fetchJSON("/api/admin/activities");

  if (!data) return;

  const activities = data.activities || [];

  if (!activitiesTable) return;

  if (!activities.length) {
    activitiesTable.innerHTML = `
      <tr>
        <td colspan="6">Henüz aktivite bulunamadı.</td>
      </tr>
    `;
    return;
  }

  activitiesTable.innerHTML = activities
    .map((item) => {
      return `
      <tr>
        <td>${item.id ?? "-"}</td>
        <td>${item.user_name ?? "-"}</td>
        <td>${item.user_email ?? "-"}</td>
        <td>${activityTypeText(item.action_type)}</td>
        <td>${item.description ?? "-"}</td>
        <td>${item.created_at ?? "-"}</td>
      </tr>
    `;
    })
    .join("");
}

listingSearch.addEventListener("input", () => {
  const query = listingSearch.value.toLowerCase().trim();

  if (!query) {
    renderLatestListings(latestListings);
    return;
  }

  const filtered = latestListings.filter((item) => {
    const text = [
      item.title,
      item.district,
      item.neighborhood,
      item.price,
      item.oda,
      item.salon,
      item.net_metrekare,
    ]
      .join(" ")
      .toLowerCase();

    return text.includes(query);
  });

  renderLatestListings(filtered);
});

logoutBtn.addEventListener("click", async () => {
  await fetchJSON("/api/admin/logout", {
    method: "POST",
  });

  window.location.href = "/admin-login";
});

runImportBtn.addEventListener("click", runImport);
runImportBtn2.addEventListener("click", runImport);

refreshStatsBtn.addEventListener("click", loadStats);
refreshListingsBtn.addEventListener("click", loadLatestListings);
refreshUsersBtn.addEventListener("click", loadUsers);

if (refreshActivitiesBtn) {
  refreshActivitiesBtn.addEventListener("click", loadActivities);
}

async function initAdmin() {
  await loadMe();
  await loadStats();
  await loadLatestListings();
  await loadUsers();
  await loadActivities();

  const statusData = await fetchJSON("/api/admin/import-status");

  if (statusData?.status?.running && !statusPoller) {
    statusPoller = setInterval(loadImportStatus, 3000);
  }
}

initAdmin();
