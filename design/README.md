# BLB dark theme design

The dark-theme redesign of the BLB (Banga-Luru Bytes) restaurant finder. Open the HTML files to see it; the colours and fonts below are the values to build from.

## What's in this folder

| File | What it is | How to open |
| --- | --- | --- |
| `desktop.html` | The full page: search form on the left, results on the right | Double-click it |
| `mobile.html` | The results screen on a phone | Double-click it |
| `theme.css` | All the styles both pages use. Every colour and font is a variable at the top | Any text editor |
| `streamlit-config.toml` | The same dark theme for the Streamlit app | Copy to `.streamlit/config.toml` |
| `README.md` | This file | |

`theme.css` must stay next to the HTML files, or the pages lose their styling. The fonts load from Google Fonts, so without internet the pages fall back to the system font.

The design was first drawn in Claude Design: https://claude.ai/artifact/12Q5esmLMnVGHKiGsCG43J

## Colours

| Name | Hex | Used for |
| --- | --- | --- |
| Background | `#0E1013` | Page |
| Header | `#12151A` | Top bar |
| Surface | `#161A20` | Cards and the search form |
| Field | `#1D222A` | Inputs, tags, chips |
| Border | `#262B35` | Card edges |
| Field border | `#2F3541` | Input edges |
| Text | `#ECEEF1` | Headings and main text |
| Body text | `#D5DAE1` | Paragraphs |
| Label text | `#C9D0DA` | Form labels |
| Muted text | `#A3ACB9` | Secondary details |
| Faint text | `#8C95A3` | Hints and footnotes |
| **Accent (saffron)** | `#F5A524` | Main button, logo, slider |
| Accent text | `#FFC35C` | Selected tags, "Liked for", rank numbers |
| Accent soft | `#2A2213` | Background of selected tags and budget |
| Text on accent | `#1A1206` | Text on the main button |
| Rating | `#12301F` bg, `#6EE7A8` text | Star rating badge |
| Info | `#13202E` bg, `#A9CFF5` text | "Included restaurants nearby" notice, "Near …" badge |
| Warning | `#F5C56B` | "Could not confirm" line |
| Live dot | `#4ADE80` | "AI ranking on" |

All text colours are readable on the dark backgrounds (contrast of at least 4.5:1).

## Fonts

- **Headings:** Space Grotesk, 600–700
- **Everything else:** Inter, 400–700, 15px base size
- Both are free on Google Fonts.

## Shapes and spacing

- Cards and the form: 16px corners, 20–24px padding
- Inputs and buttons: 10px corners, 46px tall (main button 50px)
- Tags: 8px corners; search chips are fully rounded
- Gap between cards: 16px; between form fields: 22px
- Page content is at most 1280px wide; below 600px everything stacks in one column

## How the design maps to the app

| Part of the design | Where it is in the code |
| --- | --- |
| Header: "BLB", "Banga-Luru Bytes", tagline | `app.py` — `APP_NAME`, `st.caption` in `main()` |
| "AI ranking on" pill | `app.py` — shown when an API key is set (`MISSING_KEY_MESSAGE` when not) |
| Search form | `app.py` — `show_search_form()` |
| Budget buttons (Any / Low / Medium / High) | `BUDGET_OPTIONS` in `app.py`; ranges from `ingest.py` (under ₹500, ₹500–₹1,500, over ₹1,500) |
| Search chips under "Top picks for you" | `display.py` — `search_summary()` |
| Blue notice | `result.relaxations` in `app.py` — `show_results()` |
| AI summary box | `display.py` — `summary_block()` |
| Result cards | `display.py` — `result_card()` and the `_..._STYLE` constants |
| "Near …" badge | `result_card()` — when the restaurant is outside the chosen area |
| "Could not confirm" line | `result_card()` — `item.unverified_preferences` |
| Footnote | `app.py` — `DATA_NOTE` |

## Placeholders

Text in `[brackets]` is a placeholder, such as `[Restaurant name]` and `₹[cost]`. The app fills these from the restaurant data and the AI. Ratings and area names are sample values.

## Using it in the Streamlit app

1. **Quick start:** copy `streamlit-config.toml` to `.streamlit/config.toml` and restart. The whole app turns dark with the saffron accent.
2. **Full look:** update the style constants in `display.py` (`_CARD_STYLE`, `_TITLE_STYLE` and the rest) and `FORM_STYLE` using the colours above. The card markup in `desktop.html` shows the target layout.
