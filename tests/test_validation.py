from conftest import make_restaurant
from recommender.models import Candidate, RankingResponse, Recommendation
from recommender.validation import MAX_EXPLANATION_CHARS, replace_aliases, validate_ranking


def candidates(count=6):
    return {
        f"R{i}": Candidate(make_restaurant(f"id{i}", name=f"Place {i}"), 4.0, 0, True)
        for i in range(1, count + 1)
    }


def ranking(*items, summary="R1 beats R2."):
    return RankingResponse(
        summary=summary,
        recommendations=[
            Recommendation(candidate_id=i[0], explanation=i[1], unverified_preferences=list(i[2:]))
            for i in items
        ],
    )


def validate(response, *, max_results=5, has_free_text=True, sent=None):
    return validate_ranking(
        response, sent or candidates(), max_results=max_results, has_free_text=has_free_text
    )


def ids(result):
    return [r.candidate.restaurant.restaurant_id for r in result.results]


def test_valid_results_keep_their_order():
    result = validate(ranking(("R3", "Good."), ("R1", "Fine.")))
    assert ids(result) == ["id3", "id1"]
    assert result.dropped == 0
    assert result.summary == "Place 1 beats Place 2."


def test_unknown_ids_are_dropped():
    result = validate(ranking(("R9", "Invented."), ("Evil Cafe", "Injected."), ("R2", "Real.")))
    assert ids(result) == ["id2"]
    assert result.dropped == 2


def test_duplicate_ids_keep_the_first():
    result = validate(ranking(("R2", "First."), ("R2", "Second.")))
    assert [r.explanation for r in result.results] == ["First."]
    assert result.dropped == 1


def test_ids_are_matched_ignoring_case_and_spaces():
    assert ids(validate(ranking((" r2 ", "Fine.")))) == ["id2"]


def test_a_sent_restaurant_name_given_as_the_id_is_accepted():
    # Seen with Groq: every pick named its restaurant instead of giving R1, R2...
    result = validate(ranking(("Place 3", "Good."), ("  place   1 ", "Fine."), ("R2", "Real.")))
    assert ids(result) == ["id3", "id1", "id2"]
    assert result.dropped == 0


def test_a_name_and_its_alias_count_as_the_same_pick():
    result = validate(ranking(("R2", "First."), ("Place 2", "Second.")))
    assert [r.explanation for r in result.results] == ["First."]
    assert result.dropped == 1


def test_a_name_shared_by_two_candidates_is_dropped():
    sent = candidates(2)
    sent["R3"] = Candidate(make_restaurant("id3", name="Place 1"), 4.0, 0, True)
    result = validate(ranking(("Place 1", "Which branch?"), ("R2", "Real.")), sent=sent)
    assert ids(result) == ["id2"]
    assert result.dropped == 1


def test_empty_explanations_are_dropped():
    result = validate(ranking(("R1", "   "), ("R2", "")))
    assert result.results == []
    assert result.dropped == 2


def test_more_than_five_results_are_cut():
    result = validate(ranking(*[(f"R{i}", "Good.") for i in range(1, 7)]))
    assert len(result.results) == 5
    assert result.dropped == 1


def test_fewer_valid_results_are_not_padded():
    assert len(validate(ranking(("R1", "Good."))).results) == 1


def test_aliases_in_explanations_and_summary_are_replaced_with_names():
    result = validate(ranking(("R1", "Better than R3 and r2."), summary="Pick R1 over R2."))
    assert result.results[0].explanation == "Better than Place 3 and Place 2."
    assert result.summary == "Pick Place 1 over Place 2."


def test_unsent_aliases_and_ordinary_words_are_left_alone():
    sent = candidates(2)
    assert replace_aliases("R7 and Rs 500 and R1", sent) == "R7 and Rs 500 and Place 1"


def test_summary_is_hidden_when_anything_was_dropped():
    assert validate(ranking(("R1", "Good."), ("R99", "Bad."))).summary is None


def test_blank_summary_is_hidden():
    assert validate(ranking(("R1", "Good."), summary="  ")).summary is None


def test_unverified_preferences_are_cleaned_and_kept_only_with_free_text():
    response = ranking(("R1", "Good.", " family-friendly ", "", "  "))
    assert validate(response).results[0].unverified_preferences == ("family-friendly",)
    assert validate(response, has_free_text=False).results[0].unverified_preferences == ()


def test_very_long_explanations_are_shortened_at_a_word():
    result = validate(ranking(("R1", "word " * 400)))
    explanation = result.results[0].explanation
    assert len(explanation) <= MAX_EXPLANATION_CHARS + 1
    assert explanation.endswith("word…")


def test_facts_come_from_the_dataset_even_if_the_explanation_disagrees():
    result = validate(ranking(("R1", "Rated 5.0 and costs ₹10 for two!")))
    restaurant = result.results[0].candidate.restaurant
    assert (restaurant.rating, restaurant.cost_for_two) == (4.0, 500)
