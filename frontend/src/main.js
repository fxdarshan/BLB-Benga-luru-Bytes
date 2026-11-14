// The BLB page: the search form, and results from the API.
//
// Every value from the API (dataset text, reviews and LLM text) is set with textContent, never
// innerHTML, so it always displays as text. Only the fixed icons below are markup.

import "./style.css";
import { ApiError, getHealth, getOptions, recommend, sendFeedback, shortlist } from "./api.js";
import { cuisineIcon } from "./cuisine-icons.js";
import { illustration } from "./illustrations.js";
import { parseSentence } from "./parse.js";
import { $, el, icon, notice, rise, withIcon } from "./dom.js";
import { AreaPicker, TagPicker } from "./pickers.js";
import * as logic from "./search-logic.js";
import { load, save } from "./storage.js";

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
  state.budget = logic.BUDGET_BANDS.includes(value) ? value : "any";
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

const defaultSearch = (area) => logic.defaultSearch(area, state.defaultRating);
const clampRating = (value) => logic.clampRating(value, state.defaultRating);
const searchToQuery = (search) => logic.searchToQuery(search, state.defaultRating);
const queryToSearch = (query) => logic.queryToSearch(query, state.defaultRating);
const similarSearch = (result, search) =>
  logic.similarSearch(result, search, state.options.cuisines, state.defaultRating);
const { mapsUrl, ratingBand, savedKey } = logic;

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
  // A new search may start while one is running (a refine button, an example): the newer one
  // wins, and the older one's results are ignored when they arrive.
  if (!state.options) return;
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
  // The AI takes seconds; the same search ranked by rating takes milliseconds. Show that first,
  // then swap in the AI's picks and reasons when they arrive.
  let quick = null;
  let aiDone = false;
  const ai = recommend(current);
  if (state.aiRanking !== false) {
    shortlist(current)
      .then((data) => {
        if (aiDone || run !== state.run || !data.ai_pending) return;
        quick = data;
        clearLoadingTimers();
        showStatus("Ranking with AI…", { busy: true });
        renderResults(data, current, { pending: true });
      })
      // An API without /shortlist, or a hiccup: the page simply waits for the AI, as before.
      .catch(() => {});
  }
  try {
    const data = await ai;
    aiDone = true;
    if (run !== state.run) return;
    showStatus("");
    // Swap in place: the shortlist already brought the results into view.
    renderResults(data, current, { scroll: !quick });
  } catch (error) {
    aiDone = true;
    if (run !== state.run) return;
    const message = errorMessage(error);
    if (quick) {
      // Keep the rating-ranked shortlist on screen, and say the AI's ranking didn't come.
      showStatus("");
      renderResults(quick, current, { aiError: message, scroll: false });
      return;
    }
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

function isSaved(result) {
  return state.saved.some((item) => item.key === savedKey(result));
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
  for (const option of logic.refineOptions(search, state.defaultRating)) {
    add(option.label, option.change, option.icon);
  }
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

/** Shown above the rating-ranked shortlist while the AI ranks the same search. */
function aiPendingNotice() {
  const box = el("div", "notice ai-pending");
  box.setAttribute("role", "status");
  box.append(
    el("span", "spinner"),
    el(
      "span",
      "",
      "These are the best matches by rating. The AI is ranking them now and writing why each one fits.",
    ),
  );
  return box;
}

function aiFailedNotice(message, search) {
  const box = notice(`${message} These are ranked by rating instead.`, "warn");
  const retry = el("button", "link-button", "Try again");
  retry.type = "button";
  retry.addEventListener("click", () => runSearch(search, { history: "none" }));
  box.append(retry);
  return box;
}

function renderResults(data, search, { pending = false, aiError = "", scroll = true } = {}) {
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
    if (pending) nodes.push(rise(aiPendingNotice(), 1));
    else if (aiError) nodes.push(rise(aiFailedNotice(aiError, search), 1));
    else if (data.ai_busy) nodes.push(rise(aiBusyNotice(search), 1));
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
    results.toggleAttribute("data-pending", pending);
    if (!scroll) return;
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
  state.cuisines = new TagPicker($("cuisine-box"), $("cuisine-input"), $("cuisine-list"), "cuisine", showStatus);
  state.dishes = new TagPicker($("dish-box"), $("dish-input"), $("dish-list"), "dish", showStatus);
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
