// Applies a saved light or dark choice before the page draws, so it never flashes the other
// theme. Without a saved choice the styles follow the device's setting. Kept as a separate file
// because the Content Security Policy allows no inline scripts.
try {
  const saved = JSON.parse(window.localStorage.getItem("blb:theme") || "null");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch {
  // Storage can be blocked. The device's setting then applies.
}
