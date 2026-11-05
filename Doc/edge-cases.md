# Edge Cases: AI-Powered Restaurant Recommendation System

> Design: [architecture.md](architecture.md) | Build order: [implementation-plan.md](implementation-plan.md) | Evaluation: [eval.md](eval.md)

This is the catalogue of edge cases and corner scenarios for the project, grouped by the part of the system they affect. Use it when writing code and tests in each phase.

**Nothing here has been tested yet, because no code exists.** The expected behaviour is what the app should do, and dataset cases need checking against the full data in Phase 1.

## How to Read This Document

| Status | Meaning |
| --- | --- |
| **Covered** | `architecture.md`, `implementation-plan.md` or `eval.md` already states this behaviour |
| **New** | None of those documents states this. The expected behaviour is a proposal until it is adopted. |

Unless a section says otherwise, each case should have an automated test. **(Manual)** marks a case that needs a person to check it.

## Design Gaps Now Fixed

Reviewing the documents turned up these problems, which were likely to cause real bugs. `architecture.md` and `implementation-plan.md` now include the fixes, but none has been run yet.

| # | Problem | Why it mattered | Case |
| --- | --- | --- | --- |
| 1 | The system prompt said candidates "already meet" the user's requirements, but relaxation can make that false | The LLM could tell a user that a restaurant is within budget when it isn't | [PRM-01](#prompt-building) |
| 2 | Setting `LLM_MODEL` to Haiku, which the architecture offers as a cheaper option, conflicted with `fallbacks="default"` | Every search could fail and silently fall back, with no AI explanations | [CFG-03](#configuration-and-credentials) |
| 3 | `next(...)` in the client call raised `StopIteration` if there was no text block, and the error table didn't cover this | An unhandled error instead of the score-ranked fallback | [LLM-07](#llm-responses-and-failures) |
| 4 | Candidate aliases such as `R3` could appear in explanations or the summary | Users would see meaningless internal IDs | [VAL-06](#response-validation) |
| 5 | Text repair ran before reviews were parsed, but raw reviews may hold escaped sequences such as `\x83` | `ftfy` can't see the corruption until after parsing, so it could remain | [DAT-14](#reviews) |
| 6 | An unrated restaurant scored the dataset mean `C`, which can beat well-reviewed restaurants rated below the mean | Opting in to unrated restaurants could push them above proven ones | [SCO-03](#scoring-and-the-candidate-cut) |
| 7 | Splitting "quick service" into words made "service" match nearly every review | The keyword boost would stop meaning anything | [SCO-06](#scoring-and-the-candidate-cut) |
| 8 | `</candidates>` or `</diner_notes>` in a review or free text could close the prompt's data section early | This weakened the prompt injection defence | [PRM-04](#prompt-building) |
| 9 | Pandas turns nulls into `NaN` and Parquet lists into NumPy arrays, and nothing handled this | `is None` checks, truth checks and `json.dumps` could all break | [DAT-22](#storage-and-loading) |
| 10 | The result cache was shared across Streamlit's threads with no lock, and its key ignored the data, model and prompt versions | Race conditions, and stale results after a change | [CAC-04](#result-cache) |

## Phase 1: Data Ingestion

### Ratings

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DAT-01 | `rate` is `4.1/5` or `3.6 /5` | Parses to `4.1` and `3.6` | Covered |
| DAT-02 | `rate` is `NEW` | `rating` is `None`, `is_new` is true | Covered |
| DAT-03 | `rate` is `-` or null | `rating` is `None`, `is_new` is false | Covered |
| DAT-04 | `rate` is outside 0 to 5, such as `6.0/5` | The parser returns `None` and counts it, and the ingestion check still catches any out-of-range value that gets through | Covered |
| DAT-05 | `rate` matches the pattern but isn't a number, such as `4.1.2/5` or `./5` | `[\d.]+` matches these, so catch the conversion error and return `None` | Covered |
| DAT-06 | `rate` is `new` or ` NEW ` | Trim and ignore case before comparing | Covered |

### Costs and multi-value fields

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DAT-07 | Cost is `1,300` | Parses to `1300` | Covered |
| DAT-08 | Cost is null or non-numeric | `cost_for_two` is `None` | Covered |
| DAT-09 | Cost is `0` or negative | Treat as `None`, since it can't be a real price | Covered |
| DAT-10 | A multi-value field has empty items or repeats, such as `Chinese, , Chinese,` | Drop empty items and duplicates, keeping the first order | Covered |
| DAT-11 | `Cuisines` differ only in case, and simple title-casing would turn `BBQ` into `Bbq` | Match on a lowercase key, and keep a separate display label | Covered |
| DAT-12 | `online_order` or `book_table` has something other than `Yes` or `No` | Treat as false and count it in the report | Covered |

### Reviews

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DAT-13 | `reviews_list` is `[]` or malformed | `review_snippets` is an empty list, and failures are counted | Covered |
| DAT-14 | Raw reviews hold escaped text such as `\x83`, which only becomes real characters after parsing | Run `repair_text` on review text **after** `ast.literal_eval`. Confirm against real rows in Phase 1. | Covered |
| DAT-15 | A review string is huge (about 1.28 million characters) or deeply nested | `ast.literal_eval` can raise `SyntaxError`, `ValueError`, `MemoryError` or `RecursionError`. Catch all of them, and skip strings above a size limit. | Covered |
| DAT-16 | The parsed value isn't a list of 2-item tuples | Skip bad items and keep good ones | Covered |
| DAT-17 | A review is empty after removing the `RATED` prefix | Don't keep it, so it doesn't use one of the 5 slots | Covered |
| DAT-18 | A review is longer than 300 characters | Cut at the last word boundary before the limit | Covered |
| DAT-19 | Text is still corrupted after `ftfy` | Keep it and record how much in the report | Covered |

### Run failures and checks

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DAT-20 | The raw row count isn't 51,717, a required column is missing, or under 75% of rows have a rating | Stop with a clear error | Covered |
| DAT-21 | Download fails, the disk is full, or the pinned revision no longer exists | Stop with a clear error and leave any existing output files untouched | Covered |

### Storage and loading

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DAT-22 | After loading, nulls are `NaN` and lists are NumPy arrays, so `is None` and `if array:` misbehave | Convert in one place in `repository.py`, so the rest of the code sees `None`, plain lists and Python numbers | Covered |
| DAT-23 | Sets can't be stored in Parquet | Save sorted lists, and treat them as sets on loading | Covered |
| DAT-24 | Ingestion crashes while writing, leaving a partial file | Write to a temporary file, then rename it | Covered |
| DAT-25 | `restaurants.parquet` and `metadata.json` come from different runs | Store a shared build ID in both, and show the setup message if they differ | New |
| DAT-26 | The report contains `₹` or corrupted text, and the Windows console can't print it | Set UTF-8 output, and don't let printing fail the run | Covered |
| DAT-27 | The script runs from a folder other than the project root, so `./data` points elsewhere | Resolve `DATA_DIR` from a fixed base, and print the absolute path | Covered |

### Budget bands

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DAT-28 | Costs cluster, making bands uneven | Upper edges are inclusive, and the script checks no band is nearly empty | Covered |
| DAT-29 | Clustering makes two tercile edges equal, leaving one band empty | Stop with a clear error, or move an edge to the next distinct cost | Covered |
| DAT-30 | A cost is exactly on a band edge | It belongs only to the lower band | Covered |
| DAT-31 | Extreme values such as ₹40 or ₹6,000 | They stay in the data, and the high band displays as "₹X and above" | Covered |

### Deduplication

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DED-01 | One restaurant appears under several areas and types | One record, with areas and types merged | Covered |
| DED-02 | Duplicate rows tie on votes | Use a fixed tie-break, so builds give the same result | Covered |
| DED-03 | The row with the most votes has a null rating or cost, but another row has a value | Fill the gap from the other rows, to avoid losing good data | Covered |
| DED-04 | Duplicate rows disagree on rating | Keep the highest-vote row's value, and count the conflicts in the report | Covered |
| DED-05 | Duplicate rows disagree on cuisines | Use the highest-vote row's values, and count the conflicts | Covered |
| DED-06 | The same place has a differently written address, such as `#12` and `12` | Normalise punctuation and spaces. Some misses are acceptable, so check a sample. **(Manual)** | Covered |
| DED-07 | Different outlets share a name and address, such as in a mall | They would merge. Check a sample of the largest groups. **(Manual)** | Covered |
| DED-08 | Branches of a chain share a name but not an address | They stay separate, and the card's neighbourhood distinguishes them | Covered |

## Phase 2: Preferences and Candidate Selection

### Preference validation

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| INP-01 | `area` isn't one of the 30 areas, which the UI blocks but the service could still receive | The service rejects it with a clear error, since `str` alone doesn't check this | New |
| INP-02 | `min_rating` is outside 0 to 5 | Rejected by validation | Covered |
| INP-03 | Free text is over 300 characters | Limit the input box, and have validation reject anything longer | Covered |
| INP-04 | Free text is empty or only spaces | Treat as no additional preferences, with no keyword search or empty prompt tag | New |
| INP-05 | A chosen cuisine isn't in the metadata | Rejected by validation | New |
| INP-06 | The slider gives `3.3000000000000003` | Round to one decimal place before comparing or building cache keys | New |

### Filters

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| FIL-01 | No cuisine is chosen | The cuisine filter doesn't apply | Covered |
| FIL-02 | Several cuisines are chosen | Any one match passes | Covered |
| FIL-03 | The restaurant's cuisine is null and a cuisine was chosen | Fails the filter | Covered |
| FIL-04 | Cost is null and a budget band is chosen | Fails the filter | Covered |
| FIL-05 | Cost or cuisine is null and that filter is off | Passes. The card shows "Not listed". | New |
| FIL-06 | A rating equals `min_rating` exactly | Passes, since the check is `>=` | Covered |
| FIL-07 | Unrated, with `include_unrated` off | Excluded | Covered |
| FIL-08 | Unrated, with `include_unrated` on | Included at any `min_rating` | Covered |
| FIL-09 | A restaurant is listed under the chosen area, but its `location` differs | It matches. Show its neighbourhood so the difference is clear. | Covered |
| FIL-10 | A user wants "Koramangala", but the 30 areas split it into the 4th to 7th Blocks | v1 keeps separate options, since only one area can be picked. Combining them could be later work. | New |

### Relaxation

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| REL-01 | 5 or more results before relaxing | No relaxation | Covered |
| REL-02 | 1 to 4 results | Relax in order: rating first, then budget. Stop once there are 5. | Covered |
| REL-03 | Budget is `high` or `any` | Skip the budget relaxation | Covered |
| REL-04 | `min_rating` is under 0.5 | Stop lowering at 0 | Covered |
| REL-05 | Area or cuisine would need to change | Never relaxed | Covered |
| REL-06 | Still under 5 after relaxing | Return what was found | Covered |
| REL-07 | No results after relaxing | No LLM call, and suggest changing area or cuisine | Covered |
| REL-08 | It isn't clear whether rating relaxes once or repeatedly | Once only, at most 0.5 lower, so results stay close to the request | New |
| REL-09 | Widening `low` to the next band could be read as replacing it | The result includes both `low` and `medium` | New |
| REL-10 | A relaxation adds no new restaurants | Undo it and don't report it. The plan covers only the case where the rating value doesn't change. | New |
| REL-11 | `4.1 - 0.5` gives `3.5999999999999996` | Round before filtering and displaying | New |
| REL-12 | The notice must state what changed, such as "includes 4.0+" | Use the relaxed value, and the actual rupee range for budgets | Covered |

### Scoring and the candidate cut

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| SCO-01 | A 5.0 rating with 3 votes against a 4.5 rating with 2,000 votes | The 4.5 scores higher | Covered |
| SCO-02 | `v + m` is 0, because a restaurant has no votes and the median is 0 | Use a minimum of 1 for `m`, to avoid dividing by zero | New |
| SCO-03 | An unrated restaurant scores `C`, beating a well-reviewed restaurant rated below `C` | Its weighted rating is `C - 0.25`, with the penalty tuned in Phase 6 | Covered |
| SCO-04 | A rated restaurant has 0 votes | Its score is `C`, which is correct since a rating with no votes is no evidence | New |
| SCO-05 | Scores tie | Rated before unrated, then by `restaurant_id`, so order is stable | Covered |
| SCO-06 | "quick service" splits into words, and "service" matches nearly every review | Match the full comma-separated phrase first, then its remaining words, with common review words ignored | Covered |
| SCO-07 | "bar" matches "barbecue", or "veg" matches "non-veg" | Match whole words only | New |
| SCO-08 | Free text has regex characters, such as `c++` or `(`, and would break the pattern | Escape it before matching | New |
| SCO-09 | Negative wording, such as "no buffet" or "not spicy", boosts matching restaurants | Keyword scoring can't understand this, so accept it. The small boost limits the harm, and the LLM reads the full text. | New |
| SCO-10 | Free text is only common words, or uses Hindi, Kannada or emoji | No keyword hits, and the search still works | New |
| SCO-11 | The same term matches many times | It counts as one hit, and the total is capped at 2 | Covered |
| SCO-12 | A matching review sits outside the 5 kept snippets | It won't be found. This is a known limit. | New |
| SCO-13 | Exactly 15 or 16 candidates | Never more than 15 sent | Covered |
| SCO-14 | Branches of one chain fill all 15 slots | Limit each normalised name to 3 candidates before the cut | New |

## Phase 3: User Interface

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| UI-01 | The data files are missing | Setup message naming the ingest command, with no stack trace | Covered |
| UI-02 | Parquet or metadata is corrupted or from an older format | Same setup message, asking the user to re-run ingestion | New |
| UI-03 | Changing a widget reruns the Streamlit script | Put inputs in `st.form`, so only Submit starts a search and spends money | New |
| UI-04 | The user double-clicks Submit | One search runs, with the button disabled or the cache absorbing the repeat | New |
| UI-05 | A later widget change reruns the page and could clear results | Keep the latest result in `st.session_state` | New |
| UI-06 | The user changes inputs after searching | Results stay until the next Submit, labelled with the search they came from | New |
| UI-07 | The user closes the tab during an LLM call | The call may finish and be billed. Accept this, as it should be rare. | New |
| UI-08 | Names or LLM text contain `*`, `_`, `$` or HTML | Displayed literally. `$` matters because Streamlit Markdown can treat it as maths. | Covered |
| UI-09 | Rating is missing | Shows "New" or "Unrated" | Covered |
| UI-10 | Cost or cuisine is missing | Shows "Not listed" | New |
| UI-11 | Cost could be read as per person | Always labelled "for two" | Covered |
| UI-12 | A very long name or explanation | Wraps in the card without breaking the layout. **(Manual)** | New |
| UI-13 | The neighbourhood differs from the chosen area | The card shows the neighbourhood, so it doesn't look like a wrong result | Covered |
| UI-14 | The dataset is a fixed snapshot, so places may have closed or changed | Add a short note that data may be out of date | New |
| UI-15 | Fewer than 5 results | Show them with no padding or error | Covered |

## Phase 4: LLM Integration

### Prompt building

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| PRM-01 | Relaxation means the candidates no longer meet the original request, but the system prompt says they do | Send both requested and applied limits, and tell the LLM not to claim the original limits were met | Covered |
| PRM-02 | Unrated candidates have a null rating | Send `null` with `is_new`. The LLM must say it's unrated and not imply quality. | Covered |
| PRM-03 | Values are NumPy integers or `NaN`, which break `json.dumps` or produce invalid JSON | Convert to plain Python values when loading, and use `allow_nan=False` so errors show up | Covered |
| PRM-04 | A review or free text contains `</candidates>` or `</diner_notes>` | Escape `<` and `>` as `&lt;` and `&gt;` in data before inserting it | Covered |
| PRM-05 | Free text contains an instruction, such as "ignore your instructions" | Treated as data, and validation still applies | Covered |
| PRM-06 | A review contains an injected instruction | Treated as data, and it can't add a restaurant | Covered |
| PRM-07 | A candidate has no reviews or liked dishes | Send empty lists. The explanation relies on other fields. | New |
| PRM-08 | A candidate has very long dish lists | Limit the number of dishes sent, such as 10, so token use stays predictable | New |
| PRM-09 | Only 1 candidate | Still call the LLM, since the explanation is required | New |
| PRM-10 | The system prompt must stay byte-for-byte fixed | Nothing varies in it, which keeps later caching possible | Covered |

### Free text meaning

The LLM handles these, so they belong in the [evaluation set](#phase-6-evaluation) rather than unit tests.

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| SEM-01 | Free text the data can't confirm, such as "family-friendly" | Listed in `unverified_preferences`, not claimed as met | Covered |
| SEM-02 | Free text conflicts with the form, such as "cheap" with a `high` budget | Form values stay in force, and the explanation is honest about the conflict | Covered |
| SEM-03 | Free text names another cuisine, such as "Chinese" with Italian selected | Filters stay in force. The LLM may favour restaurants that serve both. | Covered |
| SEM-04 | Free text names another location, such as "in Delhi" or a different area | Area stays in force, and the location is listed as unverified | Covered |
| SEM-05 | Real-time needs the data lacks, such as "open now" or "has parking" | Listed as unverified | Covered |
| SEM-06 | A request is unrelated, such as "write me a poem" | The schema forces a normal recommendation result, with the request ignored | Covered |
| SEM-07 | Harmful or abusive text | The app shows normal results, or score-ranked results if refused | Covered |
| SEM-08 | Conflicting wants, such as "romantic but kid-friendly" | The LLM explains the trade-off | Covered |

### LLM responses and failures

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| LLM-01 | Rate limit or server error after retries | Top 5 by score, with the "AI explanations are unavailable" notice | Covered |
| LLM-02 | Network failure or timeout | Same fallback | Covered |
| LLM-03 | `stop_reason` is `refusal` | Same fallback | Covered |
| LLM-04 | `stop_reason` is `max_tokens`, such as when thinking uses the allowance | Same fallback, with partial JSON discarded | Covered |
| LLM-05 | Invalid API key or bad request | Same fallback, logged as an error | Covered |
| LLM-06 | The response is invalid JSON or fails Pydantic | Same fallback | Covered |
| LLM-07 | The response has no text block, so `next(...)` raises `StopIteration` | Use `next(..., None)` and raise `LLMUnavailable`, which leads to the score-ranked fallback | Covered |
| LLM-08 | The response has fallback or thinking blocks before the text | Select by block type, and never assume the first block | Covered |
| LLM-09 | Wrong model ID (404), or a missing permission (403) | Same fallback, logged as a configuration error so it gets noticed | New |
| LLM-10 | Account credit or spend limit is exhausted | Same fallback, logged as an error, and it continues until topped up | New |
| LLM-11 | An unexpected exception type reaches the service | Catch it at the service boundary, log it and fall back, so a search never shows a stack trace | New |
| LLM-12 | The request takes about 90 seconds in the worst case | The spinner stays visible, then the fallback appears | Covered |
| LLM-13 | A refusal is rescued by the fallback model | The result is normal, and the log records which model served it | Covered |

### Response validation

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| VAL-01 | Unknown `candidate_id` | Dropped | Covered |
| VAL-02 | Duplicate `candidate_id` | The first is kept | Covered |
| VAL-03 | Empty explanation | Dropped. Also trim first, so a spaces-only explanation counts as empty. | Covered |
| VAL-04 | More than 5 results | First 5 kept | Covered |
| VAL-05 | Valid JSON with an empty `recommendations` list, or nothing valid left | Score-ranked fallback | Covered |
| VAL-06 | Text mentions an alias, such as "R3 is better than R1" | The prompt asks for names, and validation replaces any alias found with the restaurant's name | Covered |
| VAL-07 | ID has different case or spacing, such as `r1 ` | Trim and uppercase before matching | New |
| VAL-08 | Results were dropped, but the summary may still mention them | Hide the summary if anything was dropped, or if it's blank | New |
| VAL-09 | The explanation states a wrong fact, such as a different rating | Cards still show dataset values. The evaluation reviews the text. | Covered |
| VAL-10 | A very long explanation | Shorten for display at a safe limit, since the schema doesn't limit length | New |
| VAL-11 | `unverified_preferences` lists something the user never asked for, or has a blank item | Remove blanks. Other items are shown only when free text was entered. | New |
| VAL-12 | Fewer valid results than candidates | Show only those, with no padding from score-ranked results | Covered |

## Phase 5: Cache and Logging

### Result cache

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| CAC-01 | The same preferences twice | One LLM call | Covered |
| CAC-02 | Reordered cuisines, different case or extra spaces | Same cache entry | Covered |
| CAC-03 | A failed LLM call | Not cached | Covered |
| CAC-04 | Data is rebuilt, or the model, effort or prompt changes, within the 1-hour TTL | Include the `build_id`, model, effort and `PROMPT_VERSION` in the key | Covered |
| CAC-05 | Streamlit's threads use `TTLCache` at the same time, which isn't thread-safe | Protect reads and writes with a lock, without holding it during the LLM call | Covered |
| CAC-06 | Two users start the same uncached search together | Both may call the LLM. Accept this, since blocking adds complexity for rare savings. | New |
| CAC-07 | The result had relaxations | The cached entry includes them, so the notice still shows | New |
| CAC-08 | The cache is full, or the app restarts | Some entries are evicted, or the cache empties. Those searches then call the LLM again. | Covered |
| CAC-09 | A search with no results | Nothing to cache, since it made no API call | New |
| CAC-10 | Two free-text values differ only in punctuation | Different entries, since punctuation can change meaning | New |

### Logging

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| LOG-01 | Free text or API key could reach logs | Excluded at info level | Covered |
| LOG-02 | Exception messages may include prompt text or request details | Log the error type and status code, not the full message, at info level | New |
| LOG-03 | A cache hit, fallback or empty search has no token counts | Log the fields as null, without raising an error | New |
| LOG-04 | Writing the log line fails | Search still completes | New |
| LOG-05 | A failed request has no response `_request_id` | Log it when available, and don't assume it exists | New |

## Configuration and Credentials

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| CFG-01 | No API key | Setup message, and filtered results still work | Covered |
| CFG-02 | `ANTHROPIC_API_KEY=` is empty or only spaces | Treat as missing, rather than failing on each search | Covered |
| CFG-03 | `LLM_MODEL` is set to a model that doesn't support `fallbacks="default"`, such as Haiku 5.5 | Send `fallbacks` only for supported models, and retest when changing models | Covered |
| CFG-04 | `LLM_MODEL` is an older model that doesn't accept the same settings | The bad request falls back and is logged. Document which models are supported. | New |
| CFG-05 | `LLM_EFFORT` isn't a valid level | Stop at startup with a clear error | Covered |
| CFG-06 | A numeric setting isn't valid, such as `MAX_CANDIDATES=abc` or `0` | Stop at startup with a clear error | Covered |
| CFG-07 | `MAX_RESULTS` is higher than `MAX_CANDIDATES` | Stop at startup with a clear error | Covered |
| CFG-08 | Credentials come from an `ant auth login` profile rather than the environment | The design reads the environment only, so the app would show the setup message. Accept this, or document it. | New |
| CFG-09 | The project path has spaces, including a double space | Always quote paths in scripts and commands | New |

## Phase 6: Evaluation

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| EVL-01 | A relaxed search is checked against the original constraints | Check against the relaxed values | Covered |
| EVL-02 | An evaluation run hits the cache | The script bypasses it | Covered |
| EVL-03 | A case has no candidates | It passes if no LLM call was made and the empty message shows | Covered |
| EVL-04 | Results differ between runs, since LLM output varies | Automated checks must always hold. Run ranking comparisons several times. | Covered |
| EVL-05 | LLM failure makes a case fall back | Count it separately as a failure, not as a pass with weak results | Covered |
| EVL-06 | Rebuilding the data changes the candidates | Save the build ID with the results, so runs can be compared fairly | Covered |
| EVL-07 | A run costs more than expected | Stop once a spending cap set for the run is reached | Covered |

The semantic cases `SEM-01` to `SEM-08` should all be part of the evaluation set.

## Phase 7: Deployment

| ID | Scenario | Expected behaviour | Status |
| --- | --- | --- | --- |
| DEP-01 | The dataset licence is unresolved | Don't host publicly or publish the data | Covered |
| DEP-02 | A user refreshes the page to get around the per-session limit | The limit is only a speed bump, so the Console spend limit is the real protection | New |
| DEP-03 | The spend limit is reached | Score-ranked results continue, as in `LLM-10` | New |
| DEP-04 | The host's memory is too small | Check before launch, and drop unneeded columns if necessary | Covered |
| DEP-05 | The host restarts and loses generated data | The app rebuilds or fetches it, and the 574 MB download makes a cold start slow | New |
| DEP-06 | The host runs several instances | Each has its own cache, which is fine, but expect more LLM calls | New |
| DEP-07 | The host's secrets don't appear as environment variables | Confirm this on the chosen host, since `config.py` reads the environment | New |
| DEP-08 | The free tier puts the app to sleep | The first visit reloads the data, so it is slow. **(Manual)** | New |
