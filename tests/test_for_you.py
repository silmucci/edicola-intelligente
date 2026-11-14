"""Regressioni del feed Per te: solo metadati e passaggi locali."""

from types import SimpleNamespace

from edicola.archive import IndexChunk
from edicola.for_you import _feed_item, select_feed
from edicola.profiles import Profile


def chunk(identifier, filename, text, *, title=None, article_id=None, position=1):
    metadata = {"filename": filename, "page": 3, "position": position,
                "start": 0, "pdf_sha256": filename.ljust(64, "0"),
                "article_id": article_id}
    if title is not None:
        metadata.update(article_title=title, article_title_verified=True)
    return IndexChunk(identifier, text, metadata)


def catalog(chunks):
    files = [
        {"pdf": "old.pdf", "publication": "Testata", "date": "2026-10-20"},
        {"pdf": "new.pdf", "publication": "Testata", "date": "2026-11-09"},
    ]
    return SimpleNamespace(chunks=chunks, coverage={"files": files})


def test_real_verified_headline_survives_truncated_chunk():
    item = _feed_item(chunk("one", "new.pdf",
                      "dicata alla sicurezza. Il Comune ha annunciato il programma scolastico per il nuovo anno.",
                      title="Un programma di sicurezza nelle scuole"), ("Scuola",))
    assert item is not None
    assert item.verified_title
    assert item.title == "Un programma di sicurezza nelle scuole"
    assert "dicata" not in item.preview
    assert item.preview.startswith("Il Comune")


def test_unverified_excerpts_never_start_midword_or_invent_headline():
    item = _feed_item(chunk("two", "new.pdf",
                      "dicata alla sicurezza della scuola. I ragazzi hanno preparato elaborati grafici per un concorso nazionale. "
                      "L'iniziativa racconta il valore della prevenzione sul lavoro e della formazione degli studenti."), ())
    assert item is not None
    assert not item.verified_title
    assert item.title.startswith("I ragazzi hanno preparato")
    assert "dicata" not in item.title
    assert "L'iniziativa" in item.preview
    assert _feed_item(chunk("bad", "new.pdf", "zione e di e per la."), ()) is None


def test_recent_articles_are_listed_before_old_ones():
    items = [
        chunk("old", "old.pdf", "Il Consiglio ha approvato un nuovo piano dei trasporti per la mobilità urbana."),
        chunk("new", "new.pdf", "Il Comune ha presentato nuovi servizi di trasporto pubblico per il territorio."),
    ]
    result = select_feed(catalog(items), limit=10)
    assert [item.chunk.id for item in result] == ["new", "old"]


def test_duplicate_article_chunks_are_not_displayed_twice():
    news = (
        "Il Comune ha annunciato il progetto di riqualificazione per gli edifici scolastici. "
        "Le scuole coinvolte riceveranno interventi di manutenzione nei prossimi mesi."
    )
    items = [
        chunk("one", "new.pdf", news, article_id="article-1", position=1),
        chunk("two", "new.pdf", news + " La misura riguarda diversi quartieri della città.", article_id="article-1", position=2),
    ]
    assert len(select_feed(catalog(items))) == 1


def test_interests_and_negative_feedback_filter_the_feed():
    items = [
        chunk("school", "new.pdf", "La scuola organizza incontri per gli studenti sul tema della prevenzione."),
        chunk("sport", "new.pdf", "Lo sport giovanile torna nel calendario delle attività organizzate nel quartiere."),
    ]
    profile = Profile(interests=["scuola", "sport"], feedback={"sport": -1})
    result = select_feed(catalog(items), profile)
    assert [item.chunk.id for item in result] == ["school"]
    assert result[0].topics == ("scuola",)
    assert select_feed(catalog(items), profile, topic="sport") == []


def test_general_feed_skips_unnecessary_corpus_tokenization():
    from unittest.mock import patch
    items = [
        chunk("one", "new.pdf", "Il Comune presenta un nuovo piano per la mobilità urbana e i trasporti."),
        chunk("two", "old.pdf", "La Regione finanzia una nuova biblioteca per i cittadini e gli studenti."),
    ]
    with patch("edicola.for_you.tokens", side_effect=AssertionError("Tokenizzazione non necessaria")):
        selected = select_feed(catalog(items))
    assert [item.chunk.id for item in selected] == ["one", "two"]


def test_publication_date_is_parsed_once_per_edition():
    from datetime import date
    from unittest.mock import patch
    items = [
        chunk("old", "old.pdf", "Il Consiglio comunale approva un piano per la mobilità sostenibile."),
        chunk("new-1", "new.pdf", "La Regione presenta nuove linee di trasporto pubblico per i cittadini."),
        chunk("new-2", "new.pdf", "Il Comune rinnova il servizio scolastico per gli studenti della città."),
    ]
    with patch("edicola.for_you.date") as date_type:
        date_type.fromisoformat.side_effect = date.fromisoformat
        selected = select_feed(catalog(items))
    assert [item.chunk.id for item in selected] == ["new-1", "old", "new-2"]
    assert date_type.fromisoformat.call_count == 2



def test_masthead_is_not_displayed_as_verified_news_title_or_preview():
    header = (
        "Anno II - Numero 660 redazione@a4quotidiano.it Edizione del "
        "5/11/2026. Il Consiglio comunale ha approvato il progetto di "
        "riqualificazione delle scuole della città. L'intervento interesserà "
        "gli edifici scolastici nei quartieri periferici."
    )
    item = _feed_item(chunk(
        "header", "new.pdf", header,
        title="Anno II - Numero 660 redazione@a4quotidiano.it Edizione del 5/11/2026",
    ), ())
    assert item is not None
    assert not item.verified_title
    assert "redazione@" not in item.title
    assert item.title.startswith("Il Consiglio comunale")


def test_short_name_list_is_not_used_as_article_preview():
    item = _feed_item(chunk(
        "article", "new.pdf",
        "Horizon Service, Alberto Grazia. Gli studenti dell'istituto alberghiero "
        "hanno partecipato a un incontro dedicato all'inclusione e alla formazione.",
        title="Una giornata di inclusione per gli studenti a Roccaraso",
    ), ())
    assert item is not None
    assert item.verified_title
    assert item.preview.startswith("Gli studenti")
    assert "Horizon Service" not in item.preview


def test_only_print_header_never_becomes_a_news_card():
    assert _feed_item(chunk("masthead", "new.pdf",
        "Anno II - Numero 660 redazione@a4quotidiano.it Edizione del 5/11/2026."), ()) is None
