(function () {
  async function logout() {
    try {
      await fetch("/api/logout", {
        method: "POST",
        credentials: "same-origin",
      });
    } catch (_) {
      /* Login page will verify the session state. */
    }
    window.location.href = "/login";
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-logout-button]").forEach(function (button) {
      button.addEventListener("click", logout);
    });
  });
})();
