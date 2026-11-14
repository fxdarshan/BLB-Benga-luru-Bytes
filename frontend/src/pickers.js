// The dropdowns for area, cuisine and dish. Each opens a list on click or focus, narrows as
// the diner types, and works with the arrow keys and Enter.

import { el, icon } from "./dom.js";

// ---------- Tag pickers for cuisines and dishes ----------

// A text box with a dropdown list, like the Streamlit multiselect. The list opens on click or
// focus, narrows as the diner types, and adds a choice on click, or with the arrow keys and Enter.
// A native <datalist> isn't used because Chrome shows it only after typing starts.

export class TagPicker {
  // onStatus shows a message under the form, such as "Choose a cuisine from the list."
  constructor(box, input, list, label, onStatus = () => {}) {
    this.onStatus = onStatus;
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
    this.onStatus("");
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
      if (!quiet) this.onStatus(`Choose a ${this.label} from the list.`, { error: true });
      return;
    }
    this.input.value = "";
    if (!this.chosen.includes(match)) {
      this.chosen.push(match);
      this.render();
    }
    this.onStatus("");
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

export class AreaPicker {
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
