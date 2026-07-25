(() => {
  const storageKey = "toontown-browser.welcome-acknowledged.v1";
  let required = true;
  try {
    required = localStorage.getItem(storageKey) !== "1";
  } catch {
    // If storage is unavailable, prefer showing the notice again next visit.
  }
  document.documentElement.classList.toggle("welcome-required", required);
  window.ToontownWelcomeGate = { required, storageKey };
})();
