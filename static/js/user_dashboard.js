const userName = document.getElementById("userName");
const userEmail = document.getElementById("userEmail");
const logoutBtn = document.getElementById("logoutBtn");
const refreshBtn = document.getElementById("refreshBtn");
const activityTable = document.getElementById("activityTable");

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, options);

  if (response.status === 401) {
    window.location.href = "/login";
    return null;
  }

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.message || "İstek başarısız.");
  }

  return data;
}

function actionText(type) {
  const map = {
    register: "Kayıt",
    login: "Giriş",
    logout: "Çıkış",
    price_prediction: "Fiyat Tahmini",
    seller_analysis: "Satış Analizi",
    map_chat: "Harita Chatbot",
  };

  return map[type] || type;
}

function renderActivities(items) {
  if (!items.length) {
    activityTable.innerHTML = `
      <tr>
        <td colspan="3">Henüz aktivite bulunamadı.</td>
      </tr>
    `;
    return;
  }

  activityTable.innerHTML = items
    .map((item) => {
      return `
      <tr>
        <td>${item.created_at || "-"}</td>
        <td>${actionText(item.action_type)}</td>
        <td>${item.description || "-"}</td>
      </tr>
    `;
    })
    .join("");
}

async function loadMe() {
  const data = await fetchJSON("/api/user/me");

  if (!data || !data.user) return;

  userName.textContent = data.user.name || "Kullanıcı";
  userEmail.textContent = data.user.email || "-";
}

async function loadActivities() {
  const data = await fetchJSON("/api/user/activities");

  if (!data) return;

  renderActivities(data.activities || []);
}

logoutBtn.addEventListener("click", async () => {
  await fetchJSON("/api/user/logout", {
    method: "POST",
  });

  window.location.href = "/login";
});

refreshBtn.addEventListener("click", loadActivities);

async function init() {
  await loadMe();
  await loadActivities();
}

init();
