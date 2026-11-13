// The BLB page: the search form, and results from the API.
//
// Every value from the API (dataset text, reviews and LLM text) is set with textContent, never
// innerHTML, so it always displays as text. Only the fixed icons below are markup.

import "./style.css";
import { ApiError, getHealth, getOptions, recommend } from "./api.js";

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
  area: null,
  cuisines: null,
  dishes: null,
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
      button.append(el("span", "budget-name", budget.name), el("span", "budget-range", budget.range));
      button.addEventListener("click", () => {
        state.budget = budget.value;
        grid.querySelectorAll(".budget-option").forEach((b) => {
          b.setAttribute("aria-pressed", String(b.dataset.value === state.budget));
        });
      });
      return button;
    }),
  );
}

function fillForm(options) {
  state.area.setOptions(options.areas);
  buildBudgets(options.budgets);
  state.cuisines.setOptions(options.cuisines);
  state.dishes.setOptions(options.dishes);
  const rating = $("rating");
  rating.value = String(options.defaults.min_rating);
  showRating();
  $("extra").maxLength = options.defaults.max_additional_chars;
  submit.disabled = false;
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
    cuisines: state.cuisines.chosen,
    dishes: state.dishes.chosen,
    min_rating: Number($("rating").value),
    include_unrated: $("unrated").checked,
    additional: $("extra").value.trim(),
  };
}

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

async function onSubmit(event) {
  event.preventDefault();
  if (state.searching || submit.disabled) return;
  const search = preferences();
  state.searching = true;
  submit.disabled = true;
  results.setAttribute("aria-busy", "true");
  showStatus(state.aiRanking ? "Ranking restaurants with AI…" : "Finding restaurants…", {
    busy: true,
  });
  try {
    const data = await recommend(search);
    showStatus("");
    renderResults(data);
  } catch (error) {
    showStatus(errorMessage(error), { error: true });
  } finally {
    state.searching = false;
    submit.disabled = false;
    results.setAttribute("aria-busy", "false");
  }
}

// ---------- Results ----------

function card(result) {
  const article = el("article", "card");

  const top = el("div", "card-top");
  const title = el("div", "card-title");
  title.append(el("span", "rank", String(result.rank)), el("h3", "", result.name));
  const rating = el("span", result.is_rated ? "rating" : "rating unrated");
  // "★ 4.4 (711 votes)": the vote count is shown in a lighter style.
  const parts = /^(.*?)\s(\(.*\))$/.exec(result.rating);
  if (parts) rating.append(document.createTextNode(parts[1]), el("span", "votes", parts[2]));
  else rating.textContent = result.rating;
  top.append(title, rating);

  const meta = el("div", "card-meta");
  meta.append(el("span", "cuisines", result.cuisines), el("span", "", "·"), el("span", "", result.place));

  const badges = el("div", "badges");
  for (const badge of result.badges) badges.append(el("span", "badge", badge));
  if (result.near) badges.append(el("span", "badge badge-near", result.near));

  article.append(top, meta, badges);
  if (result.liked_for.length) {
    article.append(el("div", "liked", `Liked for: ${result.liked_for.join(", ")}`));
  }
  if (result.explanation) {
    const why = el("p", "why");
    why.append(el("b", "", "Why this fits: "), document.createTextNode(result.explanation));
    article.append(why);
  }
  if (result.review) {
    const review = el("blockquote", "review");
    review.append(el("span", "review-label", "A customer said"), document.createTextNode(`“${result.review}”`));
    article.append(review);
  }
  if (result.unverified.length) {
    const line = el("div", "unverified");
    line.append(icon("warning"), el("span", "", `Could not confirm: ${result.unverified.join(", ")}`));
    article.append(line);
  }
  return article;
}

function renderResults(data) {
  const count = data.results.length;
  const head = el("div", "results-head");
  head.append(el("h2", "", "Top picks for you"), el("span", "count", `${count} result${count === 1 ? "" : "s"}`));

  const chips = el("div", "chips");
  chips.append(el("span", "chips-label", "Results for:"));
  for (const part of data.search_summary) chips.append(el("span", "chip", part));

  const nodes = [head, rise(chips, 0)];
  for (const message of data.relaxations) nodes.push(rise(notice(message), 0));
  if (!count) {
    nodes.push(rise(notice(NO_RESULTS_MESSAGE, "warn"), 1));
  } else {
    if (data.notice) nodes.push(rise(notice(data.notice, "warn"), 1));
    if (data.summary) {
      const summary = el("div", "summary");
      const label = el("div", "summary-label");
      label.append(icon("sparkle"), document.createTextNode("AI summary"));
      summary.append(label, el("p", "", data.summary));
      nodes.push(rise(summary, 1));
    }
    data.results.forEach((result, index) => nodes.push(rise(card(result), index + 2)));
    nodes.push(rise(el("p", "footnote", DATA_NOTE), count + 2));
  }
  results.replaceChildren(...nodes);

  // On a phone the results sit below the form, so bring them into view.
  const top = results.getBoundingClientRect().top;
  if (top > window.innerHeight * 0.6) {
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    results.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  }
}

// ---------- Start ----------

function showAiStatus(on) {
  state.aiRanking = on;
  $("status-dot").classList.toggle("off", !on);
  $("status-text").textContent = on ? "AI ranking on" : "AI ranking off";
  $("status").hidden = false;
}

async function start() {
  state.area = new AreaPicker($("area"), $("area-value"), $("area-list"));
  state.cuisines = new TagPicker($("cuisine-box"), $("cuisine-input"), $("cuisine-list"), "cuisine");
  state.dishes = new TagPicker($("dish-box"), $("dish-input"), $("dish-list"), "dish");
  $("rating").addEventListener("input", showRating);
  form.addEventListener("submit", onSubmit);

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
    results.replaceChildren(notice(errorMessage(error), "error"), retry);
  }
}

start();
