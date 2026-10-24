"""Componenti locali con stili isolati: copertine cliccabili e lettore compatto."""

import streamlit as st
from edicola.design_tokens import scoped_css


GALLERY_CSS = scoped_css("""
.deck{font-family:var(--edi-sans);color:var(--edi-ink);max-width:1360px;min-width:0;width:100%}
.deck-controls{display:flex;justify-content:flex-end;gap:8px;margin:0 0 12px}
.deck-controls button{background:var(--edi-paper);color:var(--edi-primary);border:1px solid var(--edi-border);border-radius:50%;height:44px;width:44px;font:22px var(--edi-sans);cursor:pointer}
.deck-controls button:disabled{opacity:.35;cursor:default}.deck-controls button:focus-visible{outline:3px solid var(--edi-primary)}
.editions{display:grid;grid-template-columns:repeat(6,minmax(180px,1fr));grid-auto-flow:column;grid-auto-columns:minmax(180px,1fr);gap:16px;overflow-x:auto;scroll-snap-type:x mandatory;padding:4px 3px 20px;margin:0}
.edition{font:inherit;min-width:0;text-align:left;border:1px solid var(--edi-border);border-radius:var(--edi-radius);background:var(--edi-paper);padding:0;overflow:hidden;cursor:pointer;color:var(--edi-ink);transition:border-color .15s,box-shadow .15s;scroll-snap-align:start;box-shadow:var(--edi-shadow)}
.edition:hover{border-color:var(--edi-primary);box-shadow:0 8px 24px #08265412}.edition:focus-visible{outline:3px solid var(--edi-primary);outline-offset:2px}
.cover{height:292px;padding:12px;box-sizing:border-box;background:var(--edi-surface);display:flex;align-items:center;justify-content:center;border-bottom:1px solid var(--edi-border)}
.cover img{display:block;max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;box-shadow:0 2px 7px #08265420}.placeholder{color:var(--edi-muted);font-size:13px}
.description{padding:14px}.publication{font:700 17px/1.3 var(--edi-serif);overflow-wrap:anywhere;margin:0 0 6px}
.date{font-size:13px;color:var(--edi-muted);margin:0 0 12px}.bottom{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--edi-muted)}.open{color:var(--edi-primary);font-weight:650;font-size:13px}
@media(max-width:1280px){.editions{grid-template-columns:repeat(4,minmax(190px,1fr));grid-auto-columns:minmax(190px,1fr)}}
@media(max-width:1024px){.editions{grid-template-columns:repeat(3,minmax(200px,1fr));grid-auto-columns:minmax(200px,1fr)}}
@media(max-width:600px){.editions{grid-template-columns:none;grid-auto-columns:78%;gap:14px}.cover{height:320px;padding:14px}.description{padding:16px}.publication{font-size:19px}.deck-controls{margin-bottom:8px}}
@media(prefers-reduced-motion:reduce){.edition{transition:none}}
""")

GALLERY_JS = """
export default function({parentElement,data,setTriggerValue}) {
  const gallery=parentElement.querySelector('.editions'); gallery.replaceChildren();
  for(const [index,item] of data.editions.entries()) {
    const card=document.createElement('button'); card.type='button'; card.className='edition';
    card.setAttribute('aria-label',`Sfoglia ${item.title}, ${item.date}`);
    const cover=document.createElement('div'); cover.className='cover';
    if(item.thumbnail){const image=document.createElement('img');image.src='data:image/png;base64,'+item.thumbnail;image.alt='Prima pagina di '+item.title;cover.append(image);}
    else {const empty=document.createElement('span');empty.className='placeholder';empty.textContent='Copertina non disponibile';cover.append(empty);}
    const description=document.createElement('div');description.className='description';
    const title=document.createElement('h3');title.className='publication';title.textContent=item.title;
    const date=document.createElement('p');date.className='date';date.textContent=item.date;
    const bottom=document.createElement('div');bottom.className='bottom';
    const pages=document.createElement('span');pages.textContent=item.pages>0?`${item.pages} pagine`:'Edizione non consultabile';
    const action=document.createElement('span');action.className='open';action.textContent='Sfoglia →';
    bottom.append(pages,action);description.append(title,date,bottom);card.append(cover,description);
    card.onclick=()=>setTriggerValue('open_edition',index);gallery.append(card);
  }
  const previous=parentElement.querySelector('[data-scroll="previous"]'),next=parentElement.querySelector('[data-scroll="next"]');
  const update=()=>{previous.disabled=gallery.scrollLeft<=1;next.disabled=gallery.scrollLeft+gallery.clientWidth>=gallery.scrollWidth-1;};
  previous.onclick=()=>gallery.scrollBy({left:-gallery.clientWidth,behavior:'auto'});
  next.onclick=()=>gallery.scrollBy({left:gallery.clientWidth,behavior:'auto'});
  gallery.addEventListener('scroll',update);const observer=new ResizeObserver(update);observer.observe(gallery);update();
  return ()=>{observer.disconnect();gallery.removeEventListener('scroll',update);};
}
"""

READER_HTML = """
<section class="reader" aria-label="Lettore del quotidiano">
  <div class="toolbar" role="toolbar" aria-label="Controlli del quotidiano">
    <button data-action="previous" title="Pagina precedente" aria-label="Pagina precedente">←</button>
    <span class="page" aria-live="polite"></span>
    <button data-action="next" title="Pagina successiva" aria-label="Pagina successiva">→</button>
    <span class="separator"></span>
    <button data-action="fit" title="Adatta alla pagina" aria-label="Adatta alla pagina">⊡</button>
    <button data-action="minus" title="Riduci zoom" aria-label="Riduci zoom">−</button>
    <span class="zoom" aria-live="polite">100%</span>
    <button data-action="plus" title="Aumenta zoom" aria-label="Aumenta zoom">+</button>
    <span class="separator"></span>
    <button data-action="fullscreen" title="Schermo intero" aria-label="Schermo intero">⛶</button>
  </div>
  <div class="stage"><div class="paper"><img alt="Pagina del quotidiano"></div></div>
  <span class="reader-status" role="status"></span>
</section>
"""

READER_CSS = scoped_css("""
.reader{--accent:var(--edi-primary);max-width:740px;margin:0 auto;font:13px system-ui,sans-serif;color:var(--edi-ink)}
.toolbar{display:flex;align-items:center;justify-content:center;gap:4px;width:max-content;max-width:100%;margin:0 auto 12px;padding:5px 8px;background:#fff;border:1px solid #e3e7ea;border-radius:9px;box-sizing:border-box}
button{display:grid;place-items:center;width:30px;height:30px;background:transparent;border:0;border-radius:5px;color:#34434c;cursor:pointer;font:19px system-ui}
button:hover:not(:disabled){background:#edf3f5;color:var(--accent)}button:disabled{opacity:.25;cursor:default}button:focus-visible{outline:2px solid var(--accent)}
.page{min-width:52px;text-align:center;font-variant-numeric:tabular-nums}.zoom{min-width:40px;text-align:center;font-size:11px;font-variant-numeric:tabular-nums}.separator{width:1px;height:18px;background:#e3e7ea;margin:0 4px}
.stage{height:70vh;height:70dvh;max-height:780px;overflow:auto;background:var(--edi-surface);border:1px solid #e7eaed;border-radius:10px;box-sizing:border-box}
.paper{display:flex;align-items:center;justify-content:center;min-width:100%;min-height:100%;box-sizing:border-box;padding:16px}
img{display:block;flex-shrink:0;max-width:none;box-shadow:0 2px 12px #192c281c;background:white;object-fit:contain}
.reader-status{display:block;text-align:center;font-size:12px;color:var(--edi-muted);margin-top:4px}
.reader:fullscreen{max-width:none;width:100vw;height:100vh;background:var(--edi-surface);padding:12px;box-sizing:border-box}.reader:fullscreen .stage{height:calc(100vh - 76px);max-height:none}
@media(max-width:540px){.toolbar{gap:4px;padding:6px;flex-wrap:wrap;width:100%}.separator{margin:0 2px}button{width:36px;min-width:36px;height:40px}.stage{border-radius:10px}.paper{padding:10px}}
""")

READER_JS = """
export function clampZoom(zoom){return Math.max(75,Math.min(200,zoom));}
export function pageGeometry(naturalWidth,naturalHeight,areaWidth,areaHeight,zoom=100){
  if(naturalWidth<=0||naturalHeight<=0||areaWidth<=32||areaHeight<=32)return null;
  const fit=Math.min(520/naturalWidth,(areaWidth-32)/naturalWidth,(areaHeight-32)/naturalHeight);
  return {width:naturalWidth*fit*clampZoom(zoom)/100,height:naturalHeight*fit*clampZoom(zoom)/100};
}
export default function({parentElement,data,setTriggerValue}) {
  const root=parentElement.querySelector('.reader'),stage=root.querySelector('.stage'),paper=root.querySelector('.paper'),image=root.querySelector('img');
  const button=name=>root.querySelector(`[data-action="${name}"]`);
  // Zoom locale: nessun rerun o invio di dati per ingrandire la stessa pagina.
  let zoom=100;
  const layout=()=>{
    const geometry=pageGeometry(image.naturalWidth,image.naturalHeight,stage.clientWidth,stage.clientHeight,zoom);
    if(!geometry)return;
    const {width,height}=geometry;
    image.style.width=width+'px';image.style.height=height+'px';
    paper.style.width=Math.max(stage.clientWidth,width+32)+'px';paper.style.height=Math.max(stage.clientHeight,height+32)+'px';
    root.querySelector('.zoom').textContent=zoom+'%';button('minus').disabled=zoom<=75;button('plus').disabled=zoom>=200;
  };
  const changeZoom=delta=>{zoom=clampZoom(zoom+delta);layout();};
  root.querySelector('.page').textContent=`${data.page} / ${data.total}`;
  button('previous').disabled=data.page<=1;button('next').disabled=data.page>=data.total;
  button('previous').onclick=()=>setTriggerValue('page',data.page-1);button('next').onclick=()=>setTriggerValue('page',data.page+1);
  button('minus').onclick=()=>changeZoom(-25);button('plus').onclick=()=>changeZoom(25);
  button('fit').onclick=()=>{zoom=100;layout();stage.scrollTo(0,0);};
  button('fullscreen').hidden=!document.fullscreenEnabled;
  button('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await root.requestFullscreen();}
    catch{root.querySelector('.reader-status').textContent='Vista intera non disponibile.';}};
  const observer=new ResizeObserver(layout);observer.observe(stage);
  image.onload=layout;image.src='data:image/png;base64,'+data.png;image.alt=data.title+`, pagina ${data.page}`;
  return ()=>{observer.disconnect();image.onload=null;};
}
"""

gallery_component = st.components.v2.component("edicola_archive_gallery", html='<section class="deck"><nav class="deck-controls" aria-label="Scorri le edizioni"><button data-scroll="previous" aria-label="Edizioni precedenti">&#8592;</button><button data-scroll="next" aria-label="Edizioni successive">&#8594;</button></nav><div class="editions" aria-label="Edizioni disponibili"></div></section>' ,
                                               css=GALLERY_CSS, js=GALLERY_JS, isolate_styles=True)
reader_component = st.components.v2.component("edicola_archive_reader", html=READER_HTML, css=READER_CSS, js=READER_JS, isolate_styles=True)
