const loginForm = document.getElementById("loginForm");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const loginBtn = document.getElementById("loginBtn");
const loginMessage = document.getElementById("loginMessage");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  loginMessage.textContent = "";
  loginBtn.disabled = true;
  loginBtn.textContent = "Giriş yapılıyor...";

  try {
    const response = await fetch("/api/admin/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email: emailInput.value,
        password: passwordInput.value,
      }),
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      loginMessage.textContent = data.message || "Giriş başarısız.";
      return;
    }

    window.location.href = "/admin";
  } catch (error) {
    loginMessage.textContent = "Sunucuya bağlanırken hata oluştu.";
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = "Giriş Yap";
  }
});
