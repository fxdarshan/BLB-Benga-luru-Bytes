// Turns a sentence such as "pocket-friendly biryani in BTM, rated 4+, for a date night" into the search
// form's values. It runs in the browser against the real lists of areas, cuisines and dishes,
// so it is instant, needs no AI call, and can never pick a value the API would reject.

const FILLER = new Set(
  (
    "a an and any are around at best but by can find food for from get give good great i im in is " +
    "it layout like looking me my near nearby nice of on or place places please restaurant restaurants " +
    "serving serves show some somewhere something spot the to want we where which with would you"
  ).split(" "),
);

const LOW_WORDS = /\b(cheap|cheaper|budget|affordable|inexpensive|pocket[- ]friendly|low[- ]cost|economical)\b/;
const MEDIUM_WORDS = /\b(mid[- ]?range|moderate|moderately priced|mid[- ]priced|reasonable)\b/;
const HIGH_WORDS = /\b(fancy|upscale|fine[- ]dining|luxury|luxurious|expensive|premium|splurge|high[- ]end|posh)\b/;
const PRICE = /\b(?:under|below|less than|within|up ?to|max(?:imum)?|budget of)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)/;
const RATING = /\b(?:rated\s*(?:above|over|at least)?\s*)?([1-4](?:\.\d)?)\s*(?:\+|stars?|and above|or (?:more|above)|plus)/;
const RATED_AT_LEAST = /\brated\s*(?:above|over|at least)\s*([1-4](?:\.\d)?)\b/;
const TOP_RATED = /\b(top[- ]rated|highly[- ]rated|best[- ]rated|well[- ]rated)\b/;
const UNRATED = /\b(new|newly opened|unrated)\b/;

function escape(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A whole-word pattern for a name, allowing a plural "s" on the last word. */
function namePattern(name) {
  const words = name.toLowerCase().split(/\s+/).map(escape).join("\\s+");
  return new RegExp(`(?<![\\w-])${words}(?:e?s)?(?![\\w-])`);
}

/** Find names in the text, longest first, removing each match so it can't match twice. */
function takeNames(text, names) {
  const found = [];
  let rest = text;
  for (const name of [...names].sort((a, b) => b.length - a.length)) {
    const pattern = namePattern(name);
    if (pattern.test(rest)) {
      found.push(name);
      rest = rest.replace(pattern, " ");
    }
  }
  // Keep them in the order they appear in the menu (most popular first).
  found.sort((a, b) => names.indexOf(a) - names.indexOf(b));
  return { found, rest };
}

function takeArea(text, areas) {
  const exact = takeNames(text, areas);
  if (exact.found.length) return { area: exact.found[0], rest: exact.rest, guessed: false };
  // "koramangala" alone matches the first of several Koramangala blocks.
  for (const area of areas) {
    const first = area.split(/\s+/)[0];
    if (first.length >= 5 && namePattern(first).test(text)) {
      return { area, rest: text.replace(namePattern(first), " "), guessed: true };
    }
  }
  return { area: null, rest: text, guessed: false };
}

/** "Under ₹500" means the low band (below ₹500), "under 1,000" the medium one, and so on. */
function budgetFor(amount) {
  if (amount <= 500) return "low";
  if (amount <= 1500) return "medium";
  return "any";
}

/**
 * @param {string} sentence What the diner typed.
 * @param {{areas: string[], cuisines: string[], dishes: string[]}} options From GET /options.
 * @returns {{area: string|null, areaGuessed: boolean, budget: string|null, cuisines: string[],
 *   dishes: string[], min_rating: number|null, include_unrated: boolean, additional: string}}
 */
export function parseSentence(sentence, options) {
  let text = ` ${sentence.toLowerCase().replace(/[“”"]/g, " ")} `;

  const { area, rest: afterArea, guessed } = takeArea(text, options.areas);
  text = afterArea;

  const dishes = takeNames(text, options.dishes);
  text = dishes.rest;
  const cuisines = takeNames(
    text,
    options.cuisines.filter((c) => !dishes.found.some((d) => d.toLowerCase() === c.toLowerCase())),
  );
  text = cuisines.rest;

  let budget = null;
  const price = PRICE.exec(text);
  if (price) {
    budget = budgetFor(Number(price[1].replace(/,/g, "")));
    text = text.replace(price[0], " ");
  } else if (LOW_WORDS.test(text)) budget = "low";
  else if (HIGH_WORDS.test(text)) budget = "high";
  else if (MEDIUM_WORDS.test(text)) budget = "medium";
  text = text.replace(LOW_WORDS, " ").replace(HIGH_WORDS, " ").replace(MEDIUM_WORDS, " ");

  let minRating = null;
  const rating = RATING.exec(text) || RATED_AT_LEAST.exec(text);
  if (rating) {
    minRating = Math.min(4.5, Number(rating[1]));
    text = text.replace(rating[0], " ");
  } else if (TOP_RATED.test(text)) {
    minRating = 4.0;
    text = text.replace(TOP_RATED, " ");
  }

  const includeUnrated = UNRATED.test(text);
  text = text.replace(UNRATED, " ");

  // What's left, minus filler words, goes to "Anything else?" for the AI and keyword match.
  const additional = text
    .split(/[,;]+/)
    .map((part) =>
      part
        .replace(/[^\p{L}\p{N}\s'-]/gu, " ")
        .split(/\s+/)
        .filter((word) => word && !FILLER.has(word))
        .join(" "),
    )
    .filter(Boolean)
    .join(", ")
    .slice(0, 300);

  return {
    area,
    areaGuessed: guessed,
    budget,
    cuisines: cuisines.found,
    dishes: dishes.found,
    min_rating: minRating,
    include_unrated: includeUnrated,
    additional,
  };
}
