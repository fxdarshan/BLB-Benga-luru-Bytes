"""Formats search results for display. All dataset and user text is escaped here."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from recommender.cuisines import is_cuisine
from recommender.dishes import dish_pattern
from recommender.models import BudgetBand, Preferences, RankedResult, Restaurant

NOT_LISTED = "Not listed"
# About two lines on a card. Longer reviews are cut at a word, with an ellipsis.
MAX_REVIEW_CHARS = 200

# Small line icons, drawn in the text colour. Fixed markup with no dataset or user text in it.
_SPARKLE_ICON = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>'
)
_WARNING_ICON = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/></svg>'
)


def format_rating(restaurant: Restaurant) -> str:
    if restaurant.rating is not None:
        votes = f"{restaurant.votes:,} vote{'' if restaurant.votes == 1 else 's'}"
        return f"★ {restaurant.rating:.1f} ({votes})"
    return "New" if restaurant.is_new else "Unrated"


def format_cost(restaurant: Restaurant) -> str:
    if restaurant.cost_for_two is None:
        return f"Cost: {NOT_LISTED.lower()}"
    return f"₹{restaurant.cost_for_two:,} for two"


def format_cuisines(restaurant: Restaurant) -> str:
    """List real cuisines, leaving out labels such as Pizza or Cafe. A restaurant listed only with
    such labels, such as a biryani place, shows them instead, so its card still says what it
    serves."""
    cuisines = [c for c in restaurant.cuisines if is_cuisine(c)] or restaurant.cuisines
    return ", ".join(cuisines) or f"Cuisine: {NOT_LISTED.lower()}"


def budget_option_label(name: str, bands: dict[str, BudgetBand]) -> str:
    if name == "any":
        return "Any budget"
    return f"{name.capitalize()} ({bands[name].label()} for two)"


def search_summary(preferences: Preferences, bands: dict[str, BudgetBand]) -> str:
    """Describe a search in words, returned as escaped HTML."""
    parts = [preferences.area, budget_option_label(preferences.budget, bands)]
    parts.append(", ".join(preferences.cuisines) or "Any cuisine")
    if preferences.dishes:
        parts.append(", ".join(preferences.dishes))
    rating = f"Rated {preferences.min_rating:.1f}+"
    parts.append(f"{rating}, or unrated" if preferences.include_unrated else rating)
    if preferences.additional:
        parts.append(f"“{preferences.additional}”")
    chips = "".join(f'<span class="blb-chip">{escape(part)}</span>' for part in parts)
    label = '<span class="blb-search-label">Results for:</span>'
    return f'<div class="blb-search">{label}{chips}</div>'


# The BLB dark theme. Colours match design/code.html and .streamlit/config.toml; design/DESIGN.md
# lists them all. Fixed CSS from this app, with no dataset or user text in it.
FORM_STYLE = """
<style>
/* ---------- Page ---------- */
[data-testid="stMainBlockContainer"] { max-width: 1280px; padding-top: 2rem; }

/* Header: logo, name, tagline and the AI status pill. */
.blb-header {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 0.75rem 1.5rem; padding-bottom: 1.25rem; border-bottom: 1px solid #232831;
}
.blb-brand { display: flex; align-items: center; gap: 0.9rem; }
.blb-logo {
  flex: none; width: 2.75rem; height: 2.75rem; border-radius: 10px; background: #F5A524;
  color: #1A1206; display: flex; align-items: center; justify-content: center;
  font-family: "Space Grotesk", sans-serif; font-weight: 700; font-size: 0.95rem;
}
.blb-brand-name {
  margin: 0; font-family: "Space Grotesk", sans-serif; font-size: 1.4rem; font-weight: 700;
  line-height: 1.25; letter-spacing: -0.01em; color: #ECEEF1;
}
.blb-tagline { font-size: 0.85rem; color: #A3ACB9; }
.blb-status {
  display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.8rem;
  border: 1px solid #2F3541; border-radius: 999px; font-size: 0.85rem; color: #C9D0DA;
}
.blb-dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: #4ADE80; }
.blb-dot.blb-off { background: #8C95A3; }

/* Budget: a 2 x 2 grid of boxes instead of a row of round buttons. */
[data-testid="stForm"] [data-testid="stRadio"] [role="radiogroup"] {
  display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.5rem;
}
[data-testid="stForm"] [role="radiogroup"] > div {
  margin: 0 !important; min-width: 0; display: flex; align-self: stretch;
}
[data-testid="stForm"] [role="radiogroup"] [data-testid="stRadioOption"] {
  width: 100%; height: 100%; min-height: 3.5rem; margin: 0; padding: 0.5rem 0.75rem;
  box-sizing: border-box; display: flex; align-items: center; cursor: pointer;
  border: 1px solid #2F3541; border-radius: 10px; background: #1D222A;
}
[data-testid="stForm"] [role="radiogroup"] [data-testid="stRadioOption"]:has(input:checked) {
  border-color: #F5A524; background: #2A2213;
}
[data-testid="stForm"] [role="radiogroup"] [data-testid="stRadioOption"]:has(input:checked) p {
  color: #FFD58A;
}
/* The round marker is not needed: the box shows the choice. */
[data-testid="stForm"] [role="radiogroup"] [data-testid="stRadioOption"] > div > div:first-child {
  display: none;
}

/* The search form sits on a card. */
[data-testid="stForm"] {
  background: #161A20; border: 1px solid #262B35; border-radius: 16px; padding: 1.5rem;
}
/* The main button: dark text on saffron, so it stays readable. */
button[kind="primaryFormSubmit"], button[kind="primary"] {
  width: 100%; min-height: 3rem; border-radius: 12px; color: #1A1206 !important;
}
button[kind="primaryFormSubmit"] p, button[kind="primary"] p {
  color: #1A1206 !important; font-weight: 700 !important; font-size: 1rem !important;
}
/* Chosen cuisines and dishes: saffron text on a dark tag, instead of white on saffron. */
[data-baseweb="tag"] { background: #2A2213 !important; }
[data-baseweb="tag"], [data-baseweb="tag"] span, [data-baseweb="tag"] svg {
  color: #FFC35C !important;
}

/* ---------- Results ---------- */
.blb-search {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;
}
.blb-search-label { font-size: 0.85rem; color: #A3ACB9; margin-right: 0.15rem; }
.blb-chip {
  padding: 0.3rem 0.75rem; border-radius: 999px; background: #1D222A; border: 1px solid #2F3541;
  font-size: 0.85rem; color: #C9D0DA; overflow-wrap: anywhere;
}
.blb-summary {
  padding: 1.1rem 1.25rem; border-radius: 14px; background: #161A20; border: 1px solid #262B35;
  color: #D5DAE1; line-height: 1.6; overflow-wrap: anywhere;
}
.blb-summary-label, .blb-unverified { display: flex; align-items: center; gap: 0.5rem; }
.blb-summary-label {
  margin-bottom: 0.4rem; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: #FFC35C;
}
.blb-card {
  background: #161A20; border: 1px solid #262B35; border-radius: 16px; padding: 1.2rem 1.35rem;
  display: flex; flex-direction: column; gap: 0.6rem; overflow-wrap: anywhere;
}
.blb-title {
  display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
  gap: 0.5rem 1rem;
}
.blb-name {
  display: flex; align-items: center; gap: 0.75rem; min-width: 0;
  font-family: "Space Grotesk", sans-serif; font-size: 1.25rem; font-weight: 600; color: #ECEEF1;
}
.blb-rank {
  flex: none; width: 2rem; height: 2rem; border-radius: 8px; background: #232831; color: #FFC35C;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 1rem; font-weight: 700;
}
.blb-rating {
  padding: 0.25rem 0.65rem; border-radius: 8px; background: #12301F; color: #6EE7A8;
  font-size: 0.9rem; font-weight: 700; white-space: nowrap;
}
.blb-rating.blb-unrated { background: #1D222A; color: #C9D0DA; }
.blb-meta { font-size: 0.9rem; color: #A3ACB9; }
/* Cuisines are what diners scan for, so they stand out from the other details. */
.blb-cuisines { font-size: 1rem; font-weight: 700; color: #ECEEF1; }
.blb-badges { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.blb-badge {
  padding: 0.2rem 0.65rem; border-radius: 6px; background: #1D222A;
  font-size: 0.85rem; color: #C9D0DA;
}
.blb-badge.blb-near { background: #13202E; color: #A9CFF5; }
.blb-dishes { font-size: 0.95rem; font-weight: 700; color: #FFC35C; }
.blb-why {
  padding-top: 0.65rem; border-top: 1px solid #232831; color: #D5DAE1; font-size: 0.92rem;
  line-height: 1.6;
}
.blb-why b { color: #ECEEF1; }
.blb-unverified { font-size: 0.85rem; color: #F5C56B; }
/* A real customer's review, set apart so it reads as their words, not the app's. */
.blb-review {
  padding: 0.65rem 0.85rem; border-radius: 10px; background: #1D222A;
  color: #C9D0DA; font-size: 0.9rem; font-style: italic; line-height: 1.55;
}
.blb-review-label {
  display: block; margin-bottom: 0.2rem; font-style: normal; font-size: 0.72rem;
  font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #8C95A3;
}

/* ---------- Hover and selection ---------- */
/* Options in an open dropdown, larger and bold, and larger still under the cursor. */
[role="listbox"] [role="option"],
[role="listbox"] [role="option"] * { font-size: 1.05rem !important; font-weight: 600 !important; }
[role="listbox"] [role="option"]:hover,
[role="listbox"] [role="option"]:hover * {
  font-size: 1.2rem !important; font-weight: 800 !important;
}

/* What the diner has chosen: the area, cuisines, budget and checkbox. */
[data-testid="stSelectbox"] input,
[data-testid="stMultiSelectTagsContainer"] [role="group"] span,
[data-testid="stRadioOption"]:has(input:checked) p,
[data-testid="stCheckbox"] label:has(input:checked) p {
  font-size: 1.1rem !important; font-weight: 700 !important;
}

/* Anything under the cursor grows and turns bold. Scaling avoids pushing nearby items around. */
[data-testid="stRadioOption"] p,
[data-testid="stCheckbox"] label p,
[data-testid="stSelectbox"] input,
[data-testid="stMultiSelectTagsContainer"] [role="group"],
button p,
.blb-line { transition: transform 0.12s ease; transform-origin: left center; }
[data-testid="stRadioOption"]:hover p,
[data-testid="stCheckbox"] label:hover p,
[data-testid="stSelectbox"]:hover input,
[data-testid="stMultiSelectTagsContainer"] [role="group"]:hover,
button:hover p,
.blb-line:hover { transform: scale(1.08); font-weight: 700 !important; }
.blb-card { transition: border-color 0.12s ease; }
.blb-card:hover { border-color: #F5A524 !important; }
</style>
"""


def page_header(ai_ranking: bool | None) -> str:
    """The header: logo, name, tagline, and whether AI ranking is on.

    None leaves out the status, for pages shown before the settings have loaded.
    """
    status = ""
    if ai_ranking is not None:
        dot = "blb-dot" if ai_ranking else "blb-dot blb-off"
        label = "AI ranking on" if ai_ranking else "AI ranking off"
        status = f'<div class="blb-status"><span class="{dot}"></span>{label}</div>'
    return (
        '<header class="blb-header">'
        '<div class="blb-brand"><div class="blb-logo">BLB</div><div>'
        '<h1 class="blb-brand-name">Banga-Luru Bytes</h1>'
        '<div class="blb-tagline">'
        "Tell us what you're looking for, and we'll suggest where to eat.</div>"
        "</div></div>"
        f"{status}</header>"
    )


def summary_block(summary: str) -> str:
    """Show the LLM's comparison of its top choices, escaped so that it displays literally."""
    return (
        '<div class="blb-summary">'
        f'<div class="blb-summary-label">{_SPARKLE_ICON}AI summary</div>'
        f'<div class="blb-line">{escape(summary)}</div>'
        "</div>"
    )


def review_block(review: str | None) -> str:
    """Show a customer's review, escaped and cut to about two lines."""
    if not review:
        return ""
    text = review.strip()
    if len(text) > MAX_REVIEW_CHARS:
        text = text[:MAX_REVIEW_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
    return (
        '<div class="blb-review"><span class="blb-review-label">A customer said</span>'
        f"“{escape(text)}”</div>"
    )


def matched_dishes(restaurant: Restaurant, chosen: Sequence[str]) -> list[str]:
    """Return the restaurant's liked dishes or labels that match the chosen dishes."""
    patterns = [dish_pattern(d) for d in chosen]
    labels = [*restaurant.dishes, *restaurant.cuisines]
    found = [label for label in labels if any(p.search(label.casefold()) for p in patterns)]
    return list(dict.fromkeys(found))


def result_card(
    position: int, item: RankedResult, chosen_area: str, chosen_dishes: Sequence[str] = ()
) -> str:
    """Build one result card as HTML, with every value escaped so that it displays literally.

    Facts come from the dataset record. Only the explanation and unconfirmed preferences come
    from the LLM.
    """
    restaurant = item.candidate.restaurant
    place = restaurant.location or NOT_LISTED
    details = [format_cost(restaurant), *restaurant.rest_types[:2]]
    badges = "".join(f'<span class="blb-badge">{escape(d)}</span>' for d in details)
    if not item.candidate.in_chosen_area:
        badges += f'<span class="blb-badge blb-near">Near {escape(chosen_area)}</span>'
    rating_class = "blb-rating" if restaurant.rating is not None else "blb-rating blb-unrated"
    dishes = ""
    found = matched_dishes(restaurant, chosen_dishes) if chosen_dishes else []
    if found:
        listed = ", ".join(escape(d) for d in found[:4])
        dishes = f'<div class="blb-dishes">Liked for: {listed}</div>'
    explanation = ""
    if item.explanation:
        explanation = f'<div class="blb-why"><b>Why this fits:</b> {escape(item.explanation)}</div>'
    unverified = ""
    if item.unverified_preferences:
        listed = ", ".join(escape(p) for p in item.unverified_preferences)
        unverified = f'<div class="blb-unverified">{_WARNING_ICON}Could not confirm: {listed}</div>'
    return (
        '<div class="blb-card">'
        '<div class="blb-line blb-title">'
        f'<span class="blb-name"><span class="blb-rank">{position}</span>'
        f"{escape(restaurant.name)}</span>"
        f'<span class="{rating_class}">{escape(format_rating(restaurant))}</span>'
        "</div>"
        '<div class="blb-line blb-meta">'
        f'<span class="blb-cuisines">{escape(format_cuisines(restaurant))}</span>'
        f" · {escape(place)}"
        "</div>"
        f'<div class="blb-line blb-badges">{badges}</div>'
        f"{dishes}{explanation}{review_block(item.review)}{unverified}"
        "</div>"
    )
