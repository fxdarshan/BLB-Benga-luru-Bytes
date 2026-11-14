// Small helpers for building the page: the fixed icon set, and elements whose text is always
// set with textContent, so dataset, review and LLM text displays literally.

export const ICONS = {
  info: '<path d="M12 11v5M12 8h.01"/><circle cx="12" cy="12" r="9"/>',
  warning: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  pin: '<path d="M12 21s-7-6.1-7-11a7 7 0 0 1 14 0c0 4.9-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  share:
    '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
  heart:
    '<path d="M12 20s-7-4.4-9.2-8.6C1.2 8.2 3.2 4.5 6.8 4.5c2 0 3.4 1.1 5.2 3 1.8-1.9 3.2-3 5.2-3 3.6 0 5.6 3.7 4 6.9C19 15.6 12 20 12 20z"/>',
  similar: '<path d="M4 7h11M4 12h16M4 17h8"/>',
  // Form and results. Simple rounded line icons, drawn in the accent colour by the styles.
  wallet:
    '<path d="M4 7.5A2.5 2.5 0 0 1 6.5 5H17v3"/><path d="M4 7.5v9A2.5 2.5 0 0 0 6.5 19H20V9H6.5A2.5 2.5 0 0 1 4 7.5z"/><circle cx="16" cy="14" r="1.2"/>',
  bowl: '<path d="M3 11h18a9 9 0 0 1-18 0z"/><path d="M8.5 7.5c0-1.4 1-1.8 1-3.2M12.5 7.5c0-1.4 1-1.8 1-3.2"/>',
  utensils:
    '<path d="M7 3v18M4.5 3v5a2.5 2.5 0 0 0 5 0V3"/><path d="M18 21V3c-2.2 1.2-3.5 3.5-3.5 6.5V13H18"/>',
  star: '<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  chat: '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 16h-8l-4.5 3.5V16H5a1.5 1.5 0 0 1-1.5-1.5v-8A1.5 1.5 0 0 1 5 5z"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  store: '<path d="M4 10v10h16V10"/><path d="M3 10l2-6h14l2 6z"/><path d="M10 20v-5h4v5"/>',
  crown: '<path d="m3.5 8 4.5 4 4-6.5 4 6.5 4.5-4-2 10.5h-13z"/>',
  quote:
    '<path d="M9.5 7H6a1 1 0 0 0-1 1v3.5a1 1 0 0 0 1 1h3c0 2-1 3.5-3 4.5"/><path d="M19 7h-3.5a1 1 0 0 0-1 1v3.5a1 1 0 0 0 1 1h3c0 2-1 3.5-3 4.5"/>',
  bulb: '<path d="M9.5 18h5M10.5 21h3"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.1V16h5v-.1c0-.8.4-1.6 1.1-2.1A6 6 0 0 0 12 3z"/>',
  filter: '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
  reset: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 4v4.5h4.5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  trophy:
    '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4"/><path d="M12 13v4M8.5 20h7M10 17h4v3h-4z"/>',
};

export const $ = (id) => document.getElementById(id);

/** Create an element with a class and plain-text content. */
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/** One of the fixed icons above. */
export function icon(name, size = 14) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", name === "close" ? "2.5" : "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name];
  return svg;
}

/** An element holding a small icon and then its text. */
export function withIcon(tag, className, iconName, text, size = 14) {
  const node = el(tag, className);
  node.append(icon(iconName, size), el("span", "", text));
  return node;
}

/** Mark an element to rise into place at a step in the sequence. */
export function rise(node, step) {
  node.classList.add("rise");
  node.style.setProperty("--step", String(step));
  return node;
}

export function notice(text, kind = "info") {
  const box = el("div", kind === "info" ? "notice" : `notice ${kind}`);
  box.append(icon(kind === "info" ? "info" : "warning", 18), el("span", "", text));
  return box;
}
