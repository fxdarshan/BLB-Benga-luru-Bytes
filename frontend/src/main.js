// The BLB page: the search form, and results from the API.
//
// Every value from the API (dataset text, reviews and LLM text) is set with textContent, never
// innerHTML, so it always displays as text. Only the fixed icons below are markup.

import "./style.css";
import { ApiError, getHealth, getOptions, recommend, sendFeedback } from "./api.js";
import { cuisineIcon } from "./cuisine-icons.js";
import { illustration } from "./illustrations.js";
import { parseSentence } from "./parse.js";
import { load, save } from "./storage.js";

const BUDGETS = ["any", "low", "medium", "high"];
const LAST_SEARCH_KEY = "blb:last-search";
const SAVED_KEY = "blb:shortlist";
const THEME_KEY = "blb:theme"; // Also read by public/theme.js.
// A quick price sign on each budget option.
const BUDGET_TIERS = { any: "✦", low: "₹", medium: "₹₹", high: "₹₹₹" };

const NO_RESULTS_MESSAGE =
  "No restaurants match this search, even after loosening the rating and budget. " +
  "Try a different area, budget or cuisine.";
const DATA_NOTE =
  "Data comes from a fixed Zomato snapshot for Bangalore, so some places may have closed or " +
  "changed. Check before you go.";

const ICONS = {
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

const $ = (id) => document.getElementById(id);
const form = $("search-form");
const results = $("results");
const submit = $("submit");
const formStatus = $("form-status");

const state = {
  budget: "any",
  aiRanking: null,
  searching: false,
  run: 0, // The number of the latest search; see runSearch.
  area: null,
  cuisines: null,
  dishes: null,
  options: null, // From GET /options.
  defaultRating: 3.5,
  saved: [], // The shortlist, kept in this browser.
  wordsNote: "", // A note about a search typed in the diner's own words.
  loadingTimers: [],
};

// ---------- Building elements ----------

/** Create an element with a class and plain-text content. */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/** One of the fixed icons above. */
function icon(name, size = 14) {
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
function withIcon(tag, className, iconName, text, size = 14) {
  const node = el(tag, className);
  node.append(icon(iconName, size), el("span", "", text));
  return node;
}

/** Mark an element to rise into place at a step in the sequence. */
function rise(node, step) {
  node.classList.add("rise");
  node.style.setProperty("--step", String(step));
  return node;
}

function notice(text, kind = "info") {
  const box = el("div", kind === "info" ? "notice" : `notice ${kind}`);
  box.append(icon(kind === "info" ? "info" : "warning", 18), el("span", "", text));
  return box;
}

// ---------- Tag pickers for cuisines and dishes ----------

// A text box with a dropdown list, like the Streamlit multiselect. The list opens on click or
// focus, narrows as the diner types, and adds a choice on click, or with the arrow keys and Enter.
// A native <datalist> isn't used because Chrome shows it only after typing starts.

class TagPicker {
  constructor(box, input, list, label) {
    this.box = box;
    this.input = input;
    this.list = list;
    this.label = label;
    this.options = [];
    this.byKey = new Map();
    this.chosen = [];
    this.shown = [];
    this.active = -1;
    input.addEventListener("keydown", (event) => this.onKey(event));
    input.addEventListener("input", () => this.open());
    input.addEventListener("focus", () => this.open());
    input.addEventListener("click", () => this.open());
    // A click on the empty part of the box goes to the text box.
    box.addEventListener("click", (event) => {
      if (event.target === box) input.focus();
    });
    // Keep focus in the text box while an option is clicked.
    list.addEventListener("mousedown", (event) => event.preventDefault());
    list.addEventListener("click", (event) => {
      const item = event.target.closest("[role=option]");
      if (item && item.dataset.value) this.choose(item.dataset.value);
    });
    box.addEventListener("focusout", (event) => {
      if (!box.contains(event.relatedTarget)) {
        this.close();
        this.addTyped({ quiet: true });
      }
    });
  }

  setOptions(options) {
    this.options = options;
    this.byKey = new Map(options.map((o) => [o.toLowerCase(), o]));
  }

  /** Replace the chosen tags. Names not in the list are dropped. */
  setChosen(values) {
    const known = (values ?? []).map((v) => this.byKey.get(String(v).toLowerCase())).filter(Boolean);
    this.chosen = [...new Set(known)];
    this.input.value = "";
    this.render();
  }

  open() {
    const typed = this.input.value.trim().toLowerCase();
    // Keep the menu order (most popular first), with names that start with the text first.
    const left = this.options.filter((o) => !this.chosen.includes(o));
    const matches = typed ? left.filter((o) => o.toLowerCase().includes(typed)) : left;
    this.shown = typed
      ? [...matches.filter((o) => o.toLowerCase().startsWith(typed)), ...matches.filter((o) => !o.toLowerCase().startsWith(typed))]
      : matches;
    this.active = typed && this.shown.length ? 0 : -1;
    this.renderList();
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
  }

  close() {
    this.list.hidden = true;
    this.active = -1;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
  }

  renderList() {
    const id = this.list.id;
    if (!this.shown.length) {
      const empty = el("li", "tag-menu-empty", this.options.length ? `No matching ${this.label}` : "Loading…");
      this.list.replaceChildren(empty);
      this.input.removeAttribute("aria-activedescendant");
      return;
    }
    this.list.replaceChildren(
      ...this.shown.map((option, index) => {
        const item = el("li", "tag-menu-option");
        item.append(el("span", "tag-menu-option-text", option));
        item.id = `${id}-${index}`;
        item.dataset.value = option;
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", String(index === this.active));
        item.addEventListener("mouseenter", () => this.setActive(index, { scroll: false }));
        return item;
      }),
    );
    this.setActive(this.active);
  }

  setActive(index, { scroll = true } = {}) {
    this.active = index;
    const items = this.list.querySelectorAll("[role=option]");
    items.forEach((item, i) => {
      item.setAttribute("aria-selected", String(i === index));
      item.classList.toggle("active", i === index);
    });
    const current = items[index];
    if (current) {
      this.input.setAttribute("aria-activedescendant", current.id);
      if (scroll) current.scrollIntoView({ block: "nearest" });
    } else {
      this.input.removeAttribute("aria-activedescendant");
    }
  }

  choose(value) {
    if (!this.chosen.includes(value)) {
      this.chosen.push(value);
      this.render();
    }
    this.input.value = "";
    showStatus("");
    this.open();
  }

  onKey(event) {
    const isOpen = !this.list.hidden;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) return this.open();
      if (!this.shown.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = this.active < 0 ? (step > 0 ? 0 : this.shown.length - 1) : (this.active + step + this.shown.length) % this.shown.length;
      this.setActive(next);
    } else if (event.key === "Enter") {
      // Enter adds the highlighted or typed choice instead of submitting the form, unless the
      // box is empty and nothing is highlighted.
      if (isOpen && this.active >= 0) {
        event.preventDefault();
        this.choose(this.shown[this.active]);
      } else if (this.input.value.trim()) {
        event.preventDefault();
        this.addTyped({ quiet: false });
      }
    } else if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      this.close();
    } else if (event.key === "Backspace" && !this.input.value && this.chosen.length) {
      this.remove(this.chosen[this.chosen.length - 1]);
    }
  }

  addTyped({ quiet }) {
    const typed = this.input.value.trim();
    if (!typed) return;
    const match = this.byKey.get(typed.toLowerCase());
    if (!match) {
      if (!quiet) showStatus(`Choose a ${this.label} from the list.`, { error: true });
      return;
    }
    this.input.value = "";
    if (!this.chosen.includes(match)) {
      this.chosen.push(match);
      this.render();
    }
    showStatus("");
  }

  remove(value) {
    this.chosen = this.chosen.filter((v) => v !== value);
    this.render();
    this.input.focus();
    if (!this.list.hidden) this.open();
  }

  render() {
    this.box.querySelectorAll(".tag").forEach((tag) => tag.remove());
    for (const value of this.chosen) {
      const tag = el("span", "tag", value);
      const button = el("button", "tag-remove");
      button.type = "button";
      button.setAttribute("aria-label", `Remove ${value}`);
      button.append(icon("close", 12));
      button.addEventListener("click", () => this.remove(value));
      tag.append(button);
      this.box.insertBefore(tag, this.input);
    }
    this.input.placeholder = this.chosen.length ? `Add ${this.label}` : `Any ${this.label}`;
  }
}

// ---------- Area picker ----------
// A button with a dropdown list. A native <select> isn't used because its options are drawn by
// the operating system, which ignores the page's styles, so they can't grow on hover.

class AreaPicker {
  constructor(button, label, list) {
    this.button = button;
    this.label = label;
    this.list = list;
    this.options = [];
    this.active = -1;
    this.typed = "";
    this.typedAt = 0;
    button.addEventListener("click", () => (this.list.hidden ? this.open() : this.close()));
    button.addEventListener("keydown", (event) => this.onKey(event));
    list.addEventListener("mousedown", (event) => event.preventDefault());
    list.addEventListener("click", (event) => {
      const item = event.target.closest("[role=option]");
      if (item) this.choose(Number(item.dataset.index));
    });
    button.addEventListener("blur", () => this.close());
  }

  setOptions(options) {
    this.options = options;
    this.list.replaceChildren(
      ...options.map((option, index) => {
        const item = el("li", "tag-menu-option");
        item.append(el("span", "tag-menu-option-text", option));
        item.id = `${this.list.id}-${index}`;
        item.dataset.index = String(index);
        item.setAttribute("role", "option");
        item.addEventListener("mouseenter", () => this.setActive(index, { scroll: false }));
        return item;
      }),
    );
    this.choose(0, { focus: false });
    this.button.disabled = false;
  }

  /** Choose an area by name. Unknown names are ignored. */
  select(value) {
    const index = this.options.indexOf(value);
    if (index >= 0) this.choose(index, { focus: false });
    return index >= 0;
  }

  setUnavailable() {
    this.button.value = "";
    this.label.textContent = "Unavailable";
    this.button.disabled = true;
  }

  get value() {
    return this.button.value;
  }

  open() {
    if (!this.options.length) return;
    this.list.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    this.setActive(Math.max(0, this.options.indexOf(this.value)));
  }

  close() {
    this.list.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
    this.button.removeAttribute("aria-activedescendant");
  }

  setActive(index, { scroll = true } = {}) {
    this.active = index;
    const items = this.list.querySelectorAll("[role=option]");
    items.forEach((item, i) => item.classList.toggle("active", i === index));
    const current = items[index];
    if (!current) return;
    this.button.setAttribute("aria-activedescendant", current.id);
    if (scroll) current.scrollIntoView({ block: "nearest" });
  }

  choose(index, { focus = true } = {}) {
    const value = this.options[index];
    if (value === undefined) return;
    this.button.value = value;
    this.label.textContent = value;
    this.list.querySelectorAll("[role=option]").forEach((item, i) => {
      item.setAttribute("aria-selected", String(i === index));
    });
    this.close();
    if (focus) this.button.focus();
  }

  onKey(event) {
    const isOpen = !this.list.hidden;
    const last = this.options.length - 1;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) return this.open();
      const step = event.key === "ArrowDown" ? 1 : -1;
      this.setActive(Math.min(last, Math.max(0, this.active + step)));
    } else if (isOpen && (event.key === "Home" || event.key === "End")) {
      event.preventDefault();
      this.setActive(event.key === "Home" ? 0 : last);
    } else if (isOpen && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      this.choose(this.active);
    } else if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      this.close();
    } else if (event.key.length === 1 && /\S/.test(event.key)) {
      // Typing letters jumps to the first area that starts with them.
      const now = Date.now();
      this.typed = now - this.typedAt > 700 ? event.key : this.typed + event.key;
      this.typedAt = now;
      const found = this.options.findIndex((o) => o.toLowerCase().startsWith(this.typed.toLowerCase()));
      if (found >= 0) {
        if (!isOpen) this.open();
        this.setActive(found);
      }
    }
  }
}

// ---------- Form ----------

function showStatus(text, { busy = false, error = false } = {}) {
  formStatus.replaceChildren();
  formStatus.classList.toggle("error", error);
  if (busy) formStatus.append(el("span", "spinner"));
  if (text) formStatus.append(el("span", "", text));
}

function buildBudgets(budgets) {
  const grid = $("budget-grid");
  grid.replaceChildren(
    ...budgets.map((budget) => {
      const button = el("button", "budget-option");
      button.type = "button";
      button.dataset.value = budget.value;
      button.setAttribute("aria-pressed", String(budget.value === state.budget));
      button.setAttribute("aria-label", budget.label);
      const name = el("span", "budget-name", budget.name);
      const tier = el("span", "budget-tier", BUDGET_TIERS[budget.value] ?? "");
      tier.setAttribute("aria-hidden", "true");
      button.append(tier, name, el("span", "budget-range", budget.range));
      button.addEventListener("click", () => setBudget(budget.value));
      return button;
    }),
  );
}

function setBudget(value) {
  state.budget = BUDGETS.includes(value) ? value : "any";
  $("budget-grid")
    .querySelectorAll(".budget-option")
    .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === state.budget)));
}

function fillForm(options) {
  state.options = options;
  state.defaultRating = options.defaults.min_rating;
  state.area.setOptions(options.areas);
  buildBudgets(options.budgets);
  state.cuisines.setOptions(options.cuisines);
  state.dishes.setOptions(options.dishes);
  setRating(options.defaults.min_rating);
  $("extra").maxLength = options.defaults.max_additional_chars;
  submit.disabled = false;
  $("words-go").disabled = false;
}

function setRating(value) {
  $("rating").value = String(value);
  showRating();
}

function showRating() {
  $("rating-value").textContent = `★ ${Number($("rating").value).toFixed(1)}`;
}

function preferences() {
  // Anything typed but not yet added still counts, if it's a known choice.
  state.cuisines.addTyped({ quiet: true });
  state.dishes.addTyped({ quiet: true });
  return {
    area: state.area.value,
    budget: state.budget,
    cuisines: [...state.cuisines.chosen],
    dishes: [...state.dishes.chosen],
    min_rating: Number($("rating").value),
    include_unrated: $("unrated").checked,
    additional: $("extra").value.trim(),
  };
}

function defaultSearch(area) {
  return {
    area,
    budget: "any",
    cuisines: [],
    dishes: [],
    min_rating: state.defaultRating,
    include_unrated: false,
    additional: "",
  };
}

function clampRating(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return state.defaultRating;
  return Math.min(5, Math.max(0, Math.round(number * 10) / 10));
}

/** Put a search into the form. Values the lists don't know are left out. */
function setSearch(search) {
  if (search.area) state.area.select(search.area);
  setBudget(search.budget ?? "any");
  state.cuisines.setChosen(search.cuisines);
  state.dishes.setChosen(search.dishes);
  setRating(clampRating(search.min_rating ?? state.defaultRating));
  $("unrated").checked = Boolean(search.include_unrated);
  $("extra").value = String(search.additional ?? "").slice(0, 300);
}

// ---------- The search in the page address ----------
// Each search is kept in the address, such as ?area=BTM&dish=Biryani, so it can be shared or
// bookmarked, and the browser's Back button returns to the previous search.

function searchToQuery(search) {
  const params = new URLSearchParams();
  params.set("area", search.area);
  if (search.budget !== "any") params.set("budget", search.budget);
  for (const cuisine of search.cuisines) params.append("cuisine", cuisine);
  for (const dish of search.dishes) params.append("dish", dish);
  if (search.min_rating !== state.defaultRating) params.set("rating", String(search.min_rating));
  if (search.include_unrated) params.set("unrated", "1");
  if (search.additional) params.set("q", search.additional);
  return params.toString();
}

function queryToSearch(query) {
  const params = new URLSearchParams(query);
  const area = params.get("area");
  if (!area) return null;
  return {
    area,
    budget: params.get("budget") ?? "any",
    cuisines: params.getAll("cuisine"),
    dishes: params.getAll("dish"),
    min_rating: params.has("rating") ? clampRating(params.get("rating")) : state.defaultRating,
    include_unrated: params.get("unrated") === "1",
    additional: (params.get("q") ?? "").slice(0, 300),
  };
}

// ---------- Messages ----------

function errorMessage(error) {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (error.kind) {
    case "rate_limited": {
      const wait = error.retryAfter ? ` Try again in ${error.retryAfter} seconds.` : "";
      return `Too many searches.${wait || " Try again in a minute."}`;
    }
    case "invalid":
      return error.message ? `Please check the search: ${error.message}` : "Please check the search.";
    case "timeout":
      return "The search took too long. Please try again.";
    case "unavailable":
      return "Restaurant data isn't available right now. Please try again later.";
    case "network":
      return "Can't reach the restaurant service. Check your connection and try again.";
    default:
      return "The restaurant service had a problem. Please try again.";
  }
}

let toastTimer = 0;
function toast(text) {
  const box = $("toast");
  box.replaceChildren(icon("check", 16), el("span", "", text));
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), 2600);
}

// ---------- Running a search ----------

async function runSearch(search, { history = "push" } = {}) {
  if (state.searching || !state.options) return;
  setSearch(search);
  const current = preferences();
  if (!current.area) return;
  // Each search gets a number. Going home bumps it, so a search still running is then ignored.
  const run = ++state.run;
  state.searching = true;
  submit.disabled = true;
  $("words-go").disabled = true;

  const query = searchToQuery(current);
  if (history === "push" && window.location.search.slice(1) !== query) {
    window.history.pushState(null, "", `?${query}`);
  } else if (history === "replace") {
    window.history.replaceState(null, "", `?${query}`);
  }
  save(LAST_SEARCH_KEY, current);

  showStatus("Searching…", { busy: true });
  showLoading(current);
  try {
    const data = await recommend(current);
    if (run !== state.run) return;
    showStatus("");
    renderResults(data, current);
  } catch (error) {
    if (run !== state.run) return;
    const message = errorMessage(error);
    showStatus(message, { error: true });
    const retry = el("button", "btn-secondary", "Try again");
    retry.type = "button";
    retry.addEventListener("click", () => runSearch(current, { history: "none" }));
    results.replaceChildren(stateBlock("error", "That didn't work", message, retry));
  } finally {
    if (run === state.run) {
      clearLoadingTimers();
      state.searching = false;
      submit.disabled = false;
      $("words-go").disabled = false;
      results.setAttribute("aria-busy", "false");
    }
  }
}

/** Home: back to an empty form and the welcome screen, as on a first visit. The shortlist and
 *  the theme are kept, since they're the diner's own choices rather than part of a search. */
function goHome() {
  state.run += 1; // ignore any search still running
  clearLoadingTimers();
  state.searching = false;
  results.setAttribute("aria-busy", "false");
  if (!state.options) {
    window.location.assign("/");
    return;
  }
  submit.disabled = false;
  $("words-go").disabled = false;

  setSearch(defaultSearch(state.options.areas[0]));
  $("words").value = "";
  state.wordsNote = "";
  state.area.close();
  state.cuisines.close();
  state.dishes.close();
  if ($("saved-dialog").open) $("saved-dialog").close();
  showStatus("");
  save(LAST_SEARCH_KEY, null);
  if (window.location.search) window.history.pushState(null, "", window.location.pathname);

  expandForm({ scroll: false });
  showWelcome();
  window.scrollTo({ top: 0, behavior: smoothScroll() });
  toast("Fresh start. What are you in the mood for?");
}

function onSubmit(event) {
  event.preventDefault();
  if (state.searching || submit.disabled) return;
  runSearch(preferences());
}

// ---------- Loading ----------

function clearLoadingTimers() {
  state.loadingTimers.forEach(clearTimeout);
  state.loadingTimers = [];
}

/** Placeholder cards, and a line saying what the search is doing, while it runs. */
function showLoading(search) {
  clearLoadingTimers();
  const box = el("div", "loading");
  const step = el("p", "loading-step");
  const text = el("span", "", `Finding places in ${search.area}…`);
  step.append(el("span", "spinner"), text);
  box.append(step);
  for (let i = 0; i < 3; i += 1) {
    const sketch = el("div", "skeleton-card");
    sketch.setAttribute("aria-hidden", "true");
    sketch.append(el("div", "sk sk-title"), el("div", "sk sk-line"), el("div", "sk sk-line short"), el("div", "sk sk-block"));
    box.append(sketch);
  }
  results.setAttribute("aria-busy", "true");
  results.replaceChildren(box);
  if (state.aiRanking !== false) {
    state.loadingTimers.push(
      setTimeout(() => (text.textContent = "Ranking with AI and writing why each place fits…"), 1200),
      setTimeout(() => (text.textContent = "Still working. AI ranking can take up to 20 seconds…"), 9000),
    );
  }
}

// ---------- Welcome and example searches ----------

const EXAMPLES = [
  { emoji: "🍛", label: "Biryani in BTM under ₹500", search: { area: "BTM", budget: "low", dishes: ["Biryani"] } },
  { emoji: "🕯️", label: "Date night in Indiranagar", search: { area: "Indiranagar", budget: "high", additional: "romantic, date night" } },
  { emoji: "🍕", label: "Pizza in Koramangala 5th Block", search: { area: "Koramangala 5th Block", dishes: ["Pizza"] } },
  { emoji: "🥟", label: "Momos in Jayanagar", search: { area: "Jayanagar", dishes: ["Momos"] } },
  { emoji: "🫓", label: "North Indian in Whitefield", search: { area: "Whitefield", cuisines: ["North Indian"] } },
  { emoji: "🥞", label: "Masala dosa in Malleshwaram", search: { area: "Malleshwaram", dishes: ["Masala Dosa"] } },
];

function exampleIsValid({ search }) {
  const { areas, cuisines, dishes } = state.options;
  return (
    areas.includes(search.area) &&
    (search.cuisines ?? []).every((c) => cuisines.includes(c)) &&
    (search.dishes ?? []).every((d) => dishes.includes(d))
  );
}

function showWelcome() {
  const intro = el("p", "empty-state");
  intro.append(
    el("strong", "", "Your restaurant picks will appear here."),
    document.createTextNode(" Choose an area and what you feel like eating, then press "),
    el("strong", "", "Find restaurants"),
    document.createTextNode(", or try one of these:"),
  );
  const list = el("div", "examples");
  for (const example of EXAMPLES.filter(exampleIsValid)) {
    const button = el("button", "example-chip");
    const emoji = el("span", "example-emoji", example.emoji);
    emoji.setAttribute("aria-hidden", "true");
    button.append(emoji, el("span", "", example.label));
    button.type = "button";
    button.addEventListener("click", () => runSearch({ ...defaultSearch(example.search.area), ...example.search }));
    list.append(button);
  }
  const welcome = el("div", "state state-welcome");
  welcome.append(illustration("welcome"), intro, list);
  swap(() => results.replaceChildren(welcome));
}

/** A drawing, a heading, a line of text and an optional button, for empty and error states. */
function stateBlock(name, title, text, action) {
  const box = el("div", `state state-${name}`);
  box.append(illustration(name), el("h3", "state-title", title), el("p", "state-text", text));
  if (action) box.append(action);
  return box;
}

// ---------- Search in your own words ----------

function searchFromWords() {
  const text = $("words").value.trim();
  if (!text) {
    showStatus("Type what you're looking for first.", { error: true });
    $("words").focus();
    return;
  }
  const parsed = parseSentence(text, state.options);
  const area = parsed.area ?? state.area.value;
  const notes = [];
  if (!parsed.area) notes.push(`No area was named, so this searches ${area}. Change it in the form if you like.`);
  else if (parsed.areaGuessed) notes.push(`Searching ${area}. Pick another block in the form if you meant a different one.`);
  state.wordsNote = notes.join(" ");
  runSearch({
    area,
    budget: parsed.budget ?? "any",
    cuisines: parsed.cuisines,
    dishes: parsed.dishes,
    min_rating: parsed.min_rating ?? state.defaultRating,
    include_unrated: parsed.include_unrated,
    additional: parsed.additional,
  });
}

// ---------- The form on a phone ----------
// After a search on a narrow screen, the form shrinks to one line so the results are in view.

const narrowScreen = window.matchMedia("(max-width: 900px)");

function budgetName(value) {
  return state.options.budgets.find((b) => b.value === value)?.name ?? "Any budget";
}

function summaryText(search) {
  const parts = [search.area, budgetName(search.budget), ...search.cuisines, ...search.dishes];
  parts.push(`★ ${search.min_rating.toFixed(1)}+`);
  return parts.join(" · ");
}

function collapseForm(search) {
  if (!narrowScreen.matches) return;
  $("form-summary-text").textContent = summaryText(search);
  $("form-summary").hidden = false;
  form.classList.add("collapsed");
}

function expandForm({ scroll = true } = {}) {
  form.classList.remove("collapsed");
  $("form-summary").hidden = true;
  if (scroll) form.scrollIntoView({ behavior: smoothScroll(), block: "start" });
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Change the page with a short cross-fade where the browser supports it. */
function swap(change) {
  if (!document.startViewTransition || reducedMotion() || document.hidden) {
    change();
    return;
  }
  // The browser cancels the fade if the tab is hidden mid-way. The change still applies, so the
  // cancellation needs no handling beyond keeping it out of the console.
  const transition = document.startViewTransition(change);
  transition.ready.catch(() => {});
  transition.finished.catch(() => {});
}

// ---------- Light and dark theme ----------

const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");

function currentTheme() {
  return document.documentElement.dataset.theme || (prefersDark.matches ? "dark" : "light");
}

function showTheme() {
  const theme = currentTheme();
  const button = $("theme-button");
  button.dataset.current = theme;
  button.setAttribute("aria-label", theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme");
  // Match the phone's browser bar to the header.
  const bar = theme === "dark" ? "#12151a" : "#fffdf8";
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.setAttribute("content", bar));
}

function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  save(THEME_KEY, next);
  swap(() => {
    document.documentElement.dataset.theme = next;
    showTheme();
  });
}

function smoothScroll() {
  return reducedMotion() ? "auto" : "smooth";
}

// ---------- Shortlist ----------

function savedKey(result) {
  return `${result.name}|${result.place}`;
}

function isSaved(result) {
  return state.saved.some((item) => item.key === savedKey(result));
}

function mapsUrl(name, place) {
  const query = `${name}, ${place}, Bangalore`;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function setSaved(items) {
  state.saved = items;
  save(SAVED_KEY, items);
  $("saved-count").textContent = String(items.length);
  // Keep the hearts on any cards on screen in step.
  document.querySelectorAll(".save-button").forEach((button) => {
    const saved = items.some((item) => item.key === button.dataset.key);
    button.setAttribute("aria-pressed", String(saved));
    button.lastChild.textContent = saved ? "Saved" : "Save";
  });
  if ($("saved-dialog").open) renderSaved();
}

function toggleSaved(result) {
  const key = savedKey(result);
  if (isSaved(result)) {
    setSaved(state.saved.filter((item) => item.key !== key));
    toast(`Removed ${result.name} from your shortlist`);
  } else {
    const item = {
      key,
      name: result.name,
      place: result.place,
      rating: result.rating,
      cuisines: result.cuisines,
      cost: result.badges[0] ?? "",
    };
    setSaved([...state.saved, item]);
    document.querySelectorAll(".save-button").forEach((button) => {
      if (button.dataset.key !== key) return;
      button.classList.remove("pop");
      void button.offsetWidth; // restart the animation
      button.classList.add("pop");
    });
    toast(`Saved ${result.name} to your shortlist`);
  }
}

function renderSaved() {
  const body = $("saved-body");
  if (!state.saved.length) {
    body.replaceChildren(
      el("p", "empty-state", "Press ♥ Save on any restaurant to add it here and compare your favourites side by side."),
    );
    return;
  }
  const table = el("table", "compare");
  const head = el("tr");
  for (const label of ["Restaurant", "Rating", "For two", "Cuisines", "Where", ""]) {
    head.append(el("th", "", label));
  }
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const item of state.saved) {
    const row = el("tr");
    const actions = el("td", "compare-actions");
    const maps = el("a", "link-button", "Directions");
    maps.href = mapsUrl(item.name, item.place);
    maps.target = "_blank";
    maps.rel = "noopener noreferrer";
    const remove = el("button", "link-button", "Remove");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${item.name}`);
    remove.addEventListener("click", () => setSaved(state.saved.filter((s) => s.key !== item.key)));
    actions.append(maps, remove);
    row.append(
      el("td", "compare-name", item.name),
      el("td", "", item.rating),
      el("td", "", item.cost.replace(/ for two$/, "")),
      el("td", "", item.cuisines),
      el("td", "", item.place),
      actions,
    );
    tbody.append(row);
  }
  table.append(thead, tbody);
  const wrap = el("div", "table-wrap");
  wrap.append(table);
  const clear = el("button", "btn-secondary", "Clear shortlist");
  clear.type = "button";
  clear.addEventListener("click", () => setSaved([]));
  body.replaceChildren(wrap, clear);
}

// ---------- Results ----------

function ratingBand(result) {
  const value = Number((/([\d.]+)/.exec(result.rating) ?? [])[1]);
  if (!result.is_rated || !Number.isFinite(value)) return "";
  if (value >= 4) return " band-good";
  if (value >= 3.5) return " band-ok";
  return " band-low";
}

/** A search for places like this one: its main cuisine and price band, in the same area. */
function similarSearch(result, search) {
  const known = new Set(state.options.cuisines);
  const cuisine = result.cuisines.split(",").map((c) => c.trim()).find((c) => known.has(c));
  if (!cuisine) return null;
  const cost = Number(((/₹([\d,]+)/.exec(result.badges[0] ?? "") ?? [])[1] ?? "").replace(/,/g, ""));
  let budget = "any";
  if (cost > 0) budget = cost < 500 ? "low" : cost <= 1500 ? "medium" : "high";
  return { ...defaultSearch(search.area), budget, cuisines: [cuisine] };
}

async function shareResult(result) {
  const url = window.location.href;
  const text = `${result.name}: ${result.rating}, ${result.cuisines}, ${result.place}.`;
  if (navigator.share) {
    try {
      await navigator.share({ title: result.name, text, url });
    } catch {
      // The diner closed the share sheet.
    }
    return;
  }
  try {
    await navigator.clipboard.writeText(`${text} ${url}`);
    toast("Copied to the clipboard");
  } catch {
    toast("Couldn't copy. Share the page address instead.");
  }
}

function actionButton(className, iconName, label) {
  const button = el("button", `action ${className}`);
  button.type = "button";
  button.append(icon(iconName, 15), el("span", "", label));
  return button;
}

function cardActions(result, search) {
  const row = el("div", "card-actions");

  const maps = el("a", "action");
  maps.href = mapsUrl(result.name, result.place);
  maps.target = "_blank";
  maps.rel = "noopener noreferrer";
  maps.append(icon("pin", 15), el("span", "", "Directions"));

  const share = actionButton("", "share", "Share");
  share.addEventListener("click", () => shareResult(result));

  const saved = isSaved(result);
  const heart = actionButton("save-button", "heart", saved ? "Saved" : "Save");
  heart.dataset.key = savedKey(result);
  heart.setAttribute("aria-pressed", String(saved));
  heart.setAttribute("aria-label", `Save ${result.name} to your shortlist`);
  heart.addEventListener("click", () => toggleSaved(result));

  row.append(maps, share, heart);
  const similar = similarSearch(result, search);
  if (similar) {
    const more = actionButton("", "similar", "More like this");
    more.title = `${similar.cuisines[0]}, ${budgetName(similar.budget).toLowerCase()} budget, in ${search.area}`;
    more.addEventListener("click", () => runSearch(similar));
    row.append(more);
  }
  return row;
}

function feedbackRow(result, data) {
  const row = el("div", "feedback");
  const label = el("span", "feedback-label", "Was this helpful?");
  const up = el("button", "feedback-button", "👍");
  const down = el("button", "feedback-button", "👎");
  up.type = down.type = "button";
  up.setAttribute("aria-label", "Yes, this explanation was helpful");
  down.setAttribute("aria-label", "No, this explanation wasn't helpful");
  const send = async (helpful, button) => {
    up.disabled = down.disabled = true;
    button.setAttribute("aria-pressed", "true");
    try {
      await sendFeedback({
        restaurant: result.name.slice(0, 200),
        rank: result.rank,
        helpful,
        ai_ranked: data.ai_ranked,
      });
      label.textContent = "Thanks for the feedback.";
    } catch {
      label.textContent = "Couldn't send that. Please try again.";
      up.disabled = down.disabled = false;
      button.removeAttribute("aria-pressed");
    }
  };
  up.addEventListener("click", () => send(true, up));
  down.addEventListener("click", () => send(false, down));
  row.append(label, up, down);
  return row;
}

function card(result, data, search) {
  const topPick = result.rank === 1 && data.results.length > 1;
  const article = el("article", topPick ? "card top-pick" : "card");

  const top = el("div", "card-top");
  const title = el("div", "card-title");
  title.append(el("span", "rank", String(result.rank)), el("h3", "", result.name));
  if (topPick) title.append(withIcon("span", "top-pick-badge", "crown", "Top pick", 12));
  const rating = el("span", (result.is_rated ? "rating" : "rating unrated") + ratingBand(result));
  // "★ 4.4 (711 votes)": the vote count is shown in a lighter style.
  const parts = /^(.*?)\s(\(.*\))$/.exec(result.rating);
  if (parts) rating.append(document.createTextNode(parts[1]), el("span", "votes", parts[2]));
  else rating.textContent = result.rating;
  top.append(title, rating);

  const meta = el("div", "card-meta");
  const picture = el("span", "cuisine-icon", cuisineIcon(result.cuisines));
  picture.setAttribute("aria-hidden", "true");
  meta.append(picture, el("span", "cuisines", result.cuisines), el("span", "", "·"), el("span", "", result.place));

  const badges = el("div", "badges");
  result.badges.forEach((badge, index) => {
    // The first badge is the cost for two; the rest are kinds of place, such as "Cafe".
    badges.append(withIcon("span", "badge", index === 0 ? "wallet" : "store", badge, 13));
  });
  if (result.near) badges.append(withIcon("span", "badge badge-near", "pin", result.near, 13));

  article.append(top, meta, badges);
  if (result.liked_for.length) {
    article.append(withIcon("div", "liked", "heart", `Liked for: ${result.liked_for.join(", ")}`, 15));
  }
  if (result.explanation) {
    const why = el("p", "why");
    const whyLabel = el("b", "why-label");
    whyLabel.append(icon("bulb", 15), document.createTextNode("Why this fits: "));
    why.append(whyLabel, document.createTextNode(result.explanation));
    article.append(why);
  }
  if (result.review) {
    const review = el("blockquote", "review");
    review.append(withIcon("span", "review-label", "quote", "A customer said", 13), document.createTextNode(`“${result.review}”`));
    article.append(review);
  }
  if (result.unverified.length) {
    const line = el("div", "unverified");
    line.append(icon("warning"), el("span", "", `Could not confirm: ${result.unverified.join(", ")}`));
    article.append(line);
  }
  article.append(cardActions(result, search));
  if (result.explanation) article.append(feedbackRow(result, data));
  return article;
}

/** One-tap changes to the search: pocket friendly, better rated, new places, or no filters. */
function refineBar(search) {
  const bar = el("div", "refine");
  bar.append(withIcon("span", "chips-label", "filter", "Refine:", 13));
  const add = (label, change, iconName) => {
    const button = withIcon("button", "refine-button", iconName, label, 14);
    button.type = "button";
    button.addEventListener("click", () => runSearch({ ...search, ...change }));
    bar.append(button);
  };
  const lowerBudget = { high: "medium", medium: "low" }[search.budget];
  if (lowerBudget) add("Pocket friendly", { budget: lowerBudget }, "wallet");
  if (search.min_rating < 4.5) {
    const higher = Math.min(4.5, Math.floor(search.min_rating * 2) / 2 + 0.5);
    add(`Rated ${higher.toFixed(1)}+`, { min_rating: higher }, "star");
  }
  if (!search.include_unrated) add("Include new places", { include_unrated: true }, "sparkle");
  const filtered =
    search.budget !== "any" ||
    search.cuisines.length ||
    search.dishes.length ||
    search.additional ||
    search.min_rating !== state.defaultRating ||
    search.include_unrated;
  if (filtered) add("Clear filters", defaultSearch(search.area), "reset");
  return bar.childElementCount > 1 ? bar : null;
}

function aiBusyNotice(search) {
  const box = el("div", "notice warn notice-illustrated");
  box.append(
    illustration("busy", { size: "small" }),
    el(
      "span",
      "",
      "The AI is busy right now. The free plan allows only a few AI searches a minute, so these " +
        "places are ranked by rating instead. Try again in a minute for AI picks and explanations.",
    ),
  );
  const retry = el("button", "link-button", "Try again");
  retry.type = "button";
  retry.addEventListener("click", () => runSearch(search, { history: "none" }));
  box.append(retry);
  return box;
}

function renderResults(data, search) {
  const count = data.results.length;
  const head = el("div", "results-head");
  head.append(withIcon("h2", "results-title", "trophy", "Top picks for you", 22), el("span", "count", `${count} result${count === 1 ? "" : "s"}`));

  const chips = el("div", "chips");
  chips.append(withIcon("span", "chips-label", "filter", "Results for:", 13));
  for (const part of data.search_summary) chips.append(el("span", "chip", part));

  const nodes = [head, rise(chips, 0)];
  const refine = refineBar(search);
  if (refine) nodes.push(rise(refine, 0));
  if (state.wordsNote) nodes.push(rise(notice(state.wordsNote), 0));
  state.wordsNote = "";
  for (const message of data.relaxations) nodes.push(rise(notice(message), 0));
  if (!count) {
    nodes.push(rise(stateBlock("empty", "Nothing matched", NO_RESULTS_MESSAGE), 1));
  } else {
    if (data.ai_busy) nodes.push(rise(aiBusyNotice(search), 1));
    else if (data.notice) nodes.push(rise(notice(data.notice, "warn"), 1));
    if (data.summary) {
      const summary = el("div", "summary");
      const label = el("div", "summary-label");
      label.append(icon("sparkle"), document.createTextNode("AI summary"));
      summary.append(label, el("p", "", data.summary));
      nodes.push(rise(summary, 1));
    }
    data.results.forEach((result, index) => nodes.push(rise(card(result, data, search), index + 2)));
    nodes.push(rise(el("p", "footnote", DATA_NOTE), count + 2));
  }
  swap(() => {
    results.replaceChildren(...nodes);
    // On a phone the results sit below the form: shrink the form and bring the results into view.
    if (narrowScreen.matches) {
      collapseForm(search);
      form.scrollIntoView({ behavior: smoothScroll(), block: "start" });
    } else if (results.getBoundingClientRect().top > window.innerHeight * 0.6) {
      results.scrollIntoView({ behavior: smoothScroll(), block: "start" });
    }
  });
}

// ---------- Start ----------

function showAiStatus(on) {
  state.aiRanking = on;
  $("status-dot").classList.toggle("off", !on);
  $("status-text").textContent = on ? "AI ranking on" : "AI ranking off";
  $("status").hidden = false;
}

function wireUp() {
  state.area = new AreaPicker($("area"), $("area-value"), $("area-list"));
  state.cuisines = new TagPicker($("cuisine-box"), $("cuisine-input"), $("cuisine-list"), "cuisine");
  state.dishes = new TagPicker($("dish-box"), $("dish-input"), $("dish-list"), "dish");
  $("rating").addEventListener("input", showRating);
  form.addEventListener("submit", onSubmit);
  document.querySelectorAll("[data-icon]").forEach((node) => {
    node.prepend(icon(node.dataset.icon, Number(node.dataset.iconSize) || 15));
  });

  $("words-go").disabled = true;
  $("words-go").addEventListener("click", searchFromWords);
  $("words").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchFromWords();
    }
  });

  $("edit-search").addEventListener("click", () => expandForm());
  $("home-link").addEventListener("click", (event) => {
    // Let Ctrl or Cmd-click open a new tab as usual.
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    goHome();
  });
  $("theme-button").addEventListener("click", toggleTheme);
  prefersDark.addEventListener("change", showTheme);
  showTheme();
  narrowScreen.addEventListener("change", () => {
    if (!narrowScreen.matches) expandForm({ scroll: false });
  });

  const dialog = $("saved-dialog");
  $("saved-button").addEventListener("click", () => {
    renderSaved();
    dialog.showModal();
  });
  $("saved-close").addEventListener("click", () => dialog.close());
  // A click on the dimmed backdrop closes the dialog.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  setSaved(load(SAVED_KEY, []).filter((item) => item && item.key && item.name));

  window.addEventListener("popstate", () => {
    const search = queryToSearch(window.location.search);
    if (search) runSearch(search, { history: "none" });
    else showWelcome();
  });
}

async function start() {
  wireUp();
  getHealth()
    .then((health) => showAiStatus(Boolean(health.ai_ranking)))
    .catch(() => {});
  try {
    fillForm(await getOptions());
  } catch (error) {
    state.area.setUnavailable();
    const retry = el("button", "btn-primary", "Try again");
    retry.type = "button";
    retry.addEventListener("click", () => window.location.reload());
    results.replaceChildren(stateBlock("error", "Can't load the menu", errorMessage(error), retry));
    return;
  }

  // A shared or bookmarked link runs its search. Otherwise the last search is filled in.
  const fromAddress = queryToSearch(window.location.search);
  if (fromAddress && state.options.areas.includes(fromAddress.area)) {
    runSearch(fromAddress, { history: "replace" });
    return;
  }
  const last = load(LAST_SEARCH_KEY, null);
  if (last && typeof last === "object" && last.area) setSearch(last);
  showWelcome();
}

start();
