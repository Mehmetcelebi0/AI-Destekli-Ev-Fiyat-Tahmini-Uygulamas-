const registerForm = document.getElementById("registerForm");
const nameInput = document.getElementById("name");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const registerBtn = document.getElementById("registerBtn");
const registerMessage = document.getElementById("registerMessage");

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  registerMessage.textContent = "";
  registerBtn.disabled = true;
  registerBtn.textContent = "Kayıt oluşturuluyor...";

  try {
    const response = await fetch("/api/user/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: nameInput.value,
        email: emailInput.value,
        password: passwordInput.value,
      }),
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      registerMessage.textContent = data.message || "Kayıt başarısız.";
      return;
    }

    window.location.href = "/";
  } catch (error) {
    registerMessage.textContent = "Sunucuya bağlanırken hata oluştu.";
  } finally {
    registerBtn.disabled = false;
    registerBtn.textContent = "Kayıt Ol";
  }
});
