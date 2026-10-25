"""Card locali v2: CSS isolato, dati solo textContent, callback con indici verificati."""

import streamlit as st
from edicola.design_tokens import scoped_css
from edicola.product_navigation import PRODUCTS, open_product

CARD_CSS = scoped_css("""
.cards{display:grid;grid-template-columns:repeat(9,minmax(0,1fr));gap:12px;padding:6px 3px 22px;font-family:var(--edi-sans);color:var(--edi-ink);min-width:0;max-width:100%;box-sizing:border-box}
.card{font:inherit;color:inherit;min-width:0;display:flex;flex-direction:column;align-items:flex-start;text-align:left;gap:12px;background:var(--edi-paper);border:1px solid var(--edi-border);border-radius:var(--edi-radius);padding:18px 14px;box-shadow:var(--edi-shadow);cursor:pointer;transition:transform .15s,border-color .15s}
.card:hover{border-color:var(--edi-primary);transform:translateY(-2px)}.card:focus-visible{outline:3px solid var(--edi-primary);outline-offset:2px}
.card.active{border-color:var(--edi-accent);background:#fff8f8}.card svg{width:30px;height:30px;stroke:var(--edi-primary);fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.card.active svg{stroke:var(--edi-accent)}
.card h3{font:700 18px/1.2 var(--edi-serif);margin:0;overflow-wrap:anywhere}.card p{font-size:13px;line-height:1.5;color:var(--edi-muted);margin:0;flex:1}.arrow{border-radius:50%;background:var(--edi-surface);color:var(--edi-primary);width:32px;height:32px;display:grid;place-items:center}
.highlights{grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--edi-border);border-radius:var(--edi-radius);padding:8px;gap:0;background:white}
.highlights .card{box-shadow:none;border:0;border-radius:10px;padding:18px;border-right:1px solid var(--edi-border)}.highlights .card:last-child{border-right:0}.highlights .card h3{font:600 14px/1.4 var(--edi-sans);color:var(--edi-muted)}.highlights .card p{font:17px/1.45 var(--edi-serif);color:var(--edi-ink)}
@media(max-width:1280px){.cards{grid-template-columns:repeat(5,minmax(0,1fr))}.highlights{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:1024px){.cards{grid-template-columns:repeat(3,minmax(0,1fr))}.highlights{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.cards{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;padding:6px 3px 18px}.card{flex:0 0 155px;scroll-snap-align:start;min-height:184px;box-sizing:border-box;padding:16px}.highlights .card{flex-basis:85%;min-height:160px;border:0}.card h3{font-size:18px}}
@media(prefers-reduced-motion:reduce){.card{transition:none}.card:hover{transform:none}}
""")

CARD_JS = """
export default function({parentElement,data,setTriggerValue}){
 const root=parentElement.querySelector('.cards');root.replaceChildren();
 root.setAttribute('aria-label',data.mode==='highlights'?'Estratti in evidenza':'Prodotti editoriali');
 root.classList.toggle('highlights',data.mode==='highlights');
 const paths={paper:'M4 3h13v18H4z M8 7h5 M8 11h5 M8 15h5 M17 6h3v13a2 2 0 0 1-2 2',chat:'M21 11a9 9 0 0 1-9 9H4l-2 2v-8a9 9 0 1 1 19-3 M7 11h.01 M12 11h.01 M17 11h.01',document:'M5 2h14v20H5z M8 7h8 M8 11h8 M8 15h4',clock:'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18 M12 7v5l4 2',map:'M6 10a3 3 0 1 1 0 .01 M18 3a3 3 0 1 1 0 .01 M18 17a3 3 0 1 1 0 .01 M8 9l7-5 M8 11l7 7',audio:'M4 14v-3a8 8 0 0 1 16 0v3 M4 12H2v8h4v-8z M18 12h4v8h-4z',person:'M12 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8 M3 22v-3a9 9 0 0 1 18 0v3z',archive:'M3 7h18v15H3z M2 2h20v5H2z M9 11h6',list:'M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h5'};
 for(const [index,item] of data.items.entries()){
  const card=document.createElement('button');card.type='button';card.className='card';
  if(item.active){card.classList.add('active');card.setAttribute('aria-current','page');}
  if(data.mode!=='highlights'){
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
   const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[item.icon]||paths.paper);svg.append(path);card.append(svg);
  }
  const title=document.createElement('h3');title.textContent=item.title;
  const text=document.createElement('p');text.textContent=item.description;
  const arrow=document.createElement('span');arrow.className='arrow';arrow.textContent='→';arrow.setAttribute('aria-hidden','true');
  card.append(title,text,arrow);card.onclick=()=>setTriggerValue('selected',index);root.append(card);
 }
}
"""

cards_component = st.components.v2.component("edicola_editorial_cards", html='<nav class="cards" aria-label="Prodotti editoriali"></nav>',
                                              css=CARD_CSS, js=CARD_JS, isolate_styles=True)


def render_products():
    def selected():
        open_product(st.session_state.get("home_products", {}).get("selected"))
    cards_component(data={"mode": "products", "items": [{**p, "active": p["section"] == st.session_state.get("nav_section", PRODUCTS[0]["section"])} for p in PRODUCTS]},
                    key="home_products", on_selected_change=selected)


def render_highlights(items, *, metadata, context, shorten):
    from edicola.pdf_viewer import open_reference, PdfViewError
    payload = []
    for chunk in items:
        info = metadata.get(chunk.metadata["filename"], {})
        label = info.get("title", "Dall’archivio")
        if info.get("date") and info["date"] != "Data non disponibile":
            label += " · " + info["date"]
        payload.append(dict(title=label + f" · p. {chunk.metadata['page']}",
                            description="«" + shorten(chunk.text, 160) + "»"))
    def selected():
        index = st.session_state.get("home_highlights", {}).get("selected")
        if type(index) is not int or not 0 <= index < len(items):
            return
        chunk = items[index]
        try:
            open_reference(context, chunk.metadata["filename"], chunk.metadata["page"], chunk.id,
                           pdf_sha256=chunk.metadata.get("pdf_sha256"))
        except PdfViewError:
            st.session_state["pdf_navigation_error"] = "La lettura non è disponibile nell’archivio corrente."
    cards_component(data={"mode": "highlights", "items": payload}, key="home_highlights", on_selected_change=selected)
