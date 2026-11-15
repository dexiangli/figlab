(() => {
  const key = "figlab.theme";
  const system = matchMedia("(prefers-color-scheme: dark)");
  function applyTheme() {
    const stored = localStorage.getItem(key);
    const theme = ["light", "dark"].includes(stored) ? stored : (system.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById("themeToggle");
    if (button) button.textContent = theme === "dark" ? "切换浅色" : "切换深色";
  }
  applyTheme();
  system.addEventListener("change", applyTheme);
  window.addEventListener("storage", event => { if (event.key === key || event.key === null) applyTheme(); });
  document.addEventListener("DOMContentLoaded", () => {
    applyTheme();
    document.getElementById("themeToggle")?.addEventListener("click", () => {
      localStorage.setItem(key, document.documentElement.dataset.theme === "dark" ? "light" : "dark");
      applyTheme();
    });
  });
})();
