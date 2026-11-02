"""Card editoriali responsive: testo escapato e token del Task 13."""
import html
import re
from datetime import date as calendar_date
import streamlit as st
from edicola.design_tokens import TOKENS
from edicola.knowledge_presentation import short_text

LABELS = {"fact": "Fatto riferito dalla fonte", "decision": "Decisione documentata",
          "proposal": "Proposta documentata", "announced": "Annuncio / programma", "undetermined": "Stato non determinabile"}
CSS = """
.edi-event{position:relative;box-sizing:border-box;max-width:100%;border-left:2px solid var(--edi-border);padding:12px 18px 12px 24px;color:var(--edi-ink);font-family:var(--edi-sans)}
.edi-event:before{content:'';position:absolute;left:-6px;top:20px;width:10px;height:10px;border-radius:50%;background:var(--edi-primary)}
.edi-event.proposal:before{background:var(--edi-accent)}.edi-event.announced:before{background:white;border:2px solid var(--edi-primary);box-sizing:border-box}
.edi-event .event-meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap;color:var(--edi-muted);font-size:12px;margin-bottom:9px}
.edi-event time{font-size:15px;font-weight:700;color:var(--edi-primary)}
.edi-event .event-type{padding:4px 9px;border:1px solid var(--edi-border);border-radius:20px;background:var(--edi-surface)}
.edi-event.undated{border:1px solid var(--edi-border);border-radius:12px;padding:16px 18px;background:var(--edi-paper)}.edi-event.undated:before{display:none}
.edi-event h3{font:700 23px/1.3 var(--edi-serif);margin:0 0 9px;overflow-wrap:anywhere}.edi-event p{font-size:15px;line-height:1.6;margin:0;overflow-wrap:anywhere;white-space:pre-line}
.edi-event .summary-preview{display:block;font-size:15px;line-height:1.6;overflow-wrap:anywhere;white-space:pre-line}
.edi-event .summary-toggle{display:block;font-size:13px;color:var(--edi-primary);margin:6px 0}
.edi-event summary{cursor:pointer;list-style:none}.edi-event summary:focus-visible{outline:2px solid var(--edi-primary);outline-offset:4px}
.edi-event details[open] .summary-preview{display:none}
@media(max-width:600px){.edi-event{padding:12px 8px 12px 18px}.edi-event h3{font-size:20px}.edi-event .event-meta{gap:6px}}
"""


def event_text(text):
    """Rimuove i rimandi interni; le fonti sono controlli PDF dedicati."""
    return re.sub(r"\s*\[S\d+\]", "", text).strip()


def event_card(event):
    category = event.get("development_kind", "undetermined")
    category = category if category in LABELS else "undetermined"
    variables = ";".join(f"--edi-{k}:{v}" for k, v in TOKENS.items())
    date = event.get("event_date")
    layout = "dated" if date else "undated"
    if date:
        verified_date = calendar_date.fromisoformat(date)
        months = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
        readable_date = f"{verified_date.day} {months[verified_date.month - 1]} {verified_date.year}"
        date_label = f'<time datetime="{html.escape(date, quote=True)}">{readable_date}</time>'
    else:
        date_label = ""
    type_label = f'<span class="event-type">{LABELS[category]}</span>' if category != "undetermined" else ""
    description = event_text(event["description"])
    summary = f'<p>{html.escape(description)}</p>'
    if len(description) > 320:
        summary = ('<details><summary>'
                   f'<span class="summary-preview">{html.escape(short_text(description, 210))}</span>'
                   '<span class="summary-toggle">Sintesi completa · apri / chiudi</span></summary>'
                   f'{summary}</details>')
    st.html(f'<style>.edi-event{{{variables}}}{CSS}</style><article class="edi-event {category} {layout}">'
            f'<div class="event-meta">{date_label}{type_label}</div>'
            f'<h3>{html.escape(short_text(event["title"],75))}</h3>{summary}</article>')
