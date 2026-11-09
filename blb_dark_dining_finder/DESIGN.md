---
name: BLB Dark Dining Finder
colors:
  background: '#0E1013'
  header: '#12151A'
  surface: '#161A20'
  surface-field: '#1D222A'
  surface-rank: '#232831'
  border: '#262B35'
  border-field: '#2F3541'
  on-surface: '#ECEEF1'
  on-surface-body: '#D5DAE1'
  on-surface-label: '#C9D0DA'
  on-surface-muted: '#A3ACB9'
  on-surface-faint: '#8C95A3'
  primary: '#F5A524'
  on-primary: '#1A1206'
  primary-text: '#FFC35C'
  primary-soft: '#2A2213'
  rating: '#12301F'
  on-rating: '#6EE7A8'
  info: '#13202E'
  info-border: '#1F3A57'
  on-info: '#A9CFF5'
  warning-text: '#F5C56B'
  live: '#4ADE80'
typography:
  display:
    fontFamily: Space Grotesk
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline:
    fontFamily: Space Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-mobile:
    fontFamily: Space Grotesk
    fontSize: 17px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  label-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '600'
    lineHeight: 18px
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.08em
rounded:
  chip: 6px
  sm: 8px
  DEFAULT: 10px
  button: 12px
  lg: 16px
  full: 9999px
spacing:
  page-max: 1280px
  margin: 32px
  margin-mobile: 16px
  column-gap: 32px
  card-gap: 16px
  field-gap: 22px
  card-padding: 20px 22px
  form-padding: 24px
---

## Brand & Style

BLB (Banga-Luru Bytes) recommends Bangalore restaurants from a fixed Zomato snapshot, ranked by an AI. The design is a calm dark interface with one warm accent: saffron, the colour of filter coffee and biryani rice. The diner should feel helped, not sold to.

### Visual direction
- **Dark and quiet:** charcoal surfaces on a near-black page, so the few coloured details stand out.
- **One accent:** saffron marks what matters: the main button, the diner's choices, ranks and "Liked for".
- **Status colours with a single job each:** green for ratings, blue for notices and "Near …", amber for "Could not confirm".
- **No decoration for its own sake:** no gradients, photos or emoji. Line icons only.

## Colors

### Palette
- **Primary (`#F5A524`):** Saffron. The "Find restaurants" button, the logo, the rating slider and the selected budget's border.
- **Primary text (`#FFC35C`):** Lighter saffron for text: chosen cuisines and dishes, rank numbers, "Liked for", the "AI summary" label.
- **Primary soft (`#2A2213`):** The background behind chosen tags and the selected budget.
- **On primary (`#1A1206`):** Dark text on saffron. White on saffron is too faint to read.

### Surfaces, darkest to lightest
- `background` `#0E1013`: the page
- `header` `#12151A`: the top bar
- `surface` `#161A20`: cards, the search form, the AI summary
- `surface-field` `#1D222A`: inputs, chips, badges
- `surface-rank` `#232831`: the rank box and dividers inside cards

### Text, brightest to faintest
- `on-surface` `#ECEEF1`: headings, restaurant names, cuisines
- `on-surface-body` `#D5DAE1`: paragraphs ("Why this fits", the AI summary)
- `on-surface-label` `#C9D0DA`: form labels, chips, badges
- `on-surface-muted` `#A3ACB9`: locations, counts
- `on-surface-faint` `#8C95A3`: hints, placeholders, the data footnote

Every text colour has a contrast ratio of at least 4.5:1 against the surface it sits on.

### Status
- **Rating:** `#6EE7A8` on `#12301F`. Unrated restaurants use `on-surface-label` on `surface-field`.
- **Info:** `#A9CFF5` on `#13202E` with a `#1F3A57` border, for the relaxation notice and the "Near …" badge.
- **Warning:** `#F5C56B` text with a warning icon, for "Could not confirm".
- **Live:** `#4ADE80` dot in the "AI ranking on" pill.

## Typography

**Space Grotesk** for headings and restaurant names gives the app its character. **Inter** for everything else keeps forms and long explanations easy to read. Both are on Google Fonts.

- Page heading "Top picks for you": Space Grotesk 26px / 600
- Form heading and restaurant names: Space Grotesk 20px / 600 (17px on phones)
- Body: Inter 15px; card details 14px
- Labels: Inter 13px / 600
- Section labels such as "AI SUMMARY": Inter 12px / 700, uppercase, 0.08em letter spacing

## Layout & Spacing

- **Desktop (over 600px):** content up to 1280px wide with 32px margins. The search form on the left (340–420px wide), results on the right taking the rest, 32px apart.
- **Phone (600px and under):** one column with 16px margins, the form first and the results below. Nothing scrolls sideways.
- Cards are 16px apart; form fields are 22px apart.
- Every control is at least 44px tall, so it is easy to tap.

## Elevation & Depth

Flat. Depth comes from the surface steps and 1px borders, not shadows.
- **Level 0:** the page, `#0E1013`
- **Level 1:** cards and the form, `#161A20` with a `#262B35` border
- **Level 2:** inputs and chips inside them, `#1D222A` with a `#2F3541` border
- **Hover:** a card's border turns saffron.

## Shapes

- Badges inside cards: 6px
- Tags, the rank box and rating badges: 8px
- Inputs and budget buttons: 10px
- The main button: 12px
- Cards and the search form: 16px
- Search chips and the status pill: fully rounded

## Components

### Header
The saffron "BLB" logo square, "Banga-Luru Bytes" in Space Grotesk, the tagline in muted text, and an "AI ranking on" pill on the right. When no API key is set, the app shows a notice saying ranking is by score instead.

### Search form
A card titled "Find a place to eat" with, in order: area dropdown, budget, cuisine tags, dish tags, minimum rating slider, the "Include new and unrated restaurants" checkbox, the optional "Anything else?" box, and the full-width saffron "Find restaurants" button with a search icon.
- **Budget:** four options in a 2×2 grid, each showing its range: Any budget (no limit), Low (under ₹500), Medium (₹500–₹1,500), High (over ₹1,500). The selected one has a saffron border on `primary-soft`.
- **Tags:** chosen cuisines and dishes are saffron text on `primary-soft`, with a × to remove.

### Search summary
"Results for:" followed by one rounded chip per choice: area, budget, cuisines, dishes, minimum rating, and the "Anything else?" text in quotes.

### AI summary
A card with a sparkle icon and the "AI SUMMARY" label in saffron, then the AI's comparison of its top picks.

### Result card
1. The rank in a small saffron-on-dark box, the restaurant name, and the green rating badge, such as "★ 4.4 (1,812 votes)", "New" or "Unrated".
2. Cuisines in bold, then the location in muted text.
3. Badges: cost for two, up to two restaurant types, and a blue "Near …" badge when it is outside the chosen area.
4. "Liked for: …" in saffron, when the diner picked dishes.
5. A divider, then "**Why this fits:**" with the AI's explanation.
6. "Could not confirm: …" in amber with a warning icon, when the AI could not check a request.

### Notices and footnote
Blue info notices for searches that were loosened. The footnote under the results says the data is a fixed Zomato snapshot, so places may have closed or changed.

## In the app

| Design | Code |
| --- | --- |
| Colours and fonts for Streamlit's own widgets | `.streamlit/config.toml` (`[theme]`) |
| Form card, button, tags and all result styles | `FORM_STYLE` in `src/recommender/display.py` |
| Result card markup | `result_card()` in `src/recommender/display.py` |
| AI summary | `summary_block()` in `src/recommender/display.py` |
| Search summary chips | `search_summary()` in `src/recommender/display.py` |
| Header, form, two-column layout | `main()` and `show_search_form()` in `app.py` |

Text in `[brackets]` in `code.html`, such as `[Restaurant name]`, is a placeholder that the app fills from the data and the AI.
