"""Componenti locali con stili isolati: copertine cliccabili e lettore compatto."""

import streamlit as st


GALLERY_CSS = """
.editions{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:24px;max-width:1120px;margin:8px 0 28px;font-family:system-ui,sans-serif}
.edition{font:inherit;min-width:0;text-align:left;border:1px solid #e2e5e9;border-radius:12px;background:#fff;padding:0;overflow:hidden;cursor:pointer;color:#17252f;transition:border-color .15s,box-shadow .15s}
.edition:hover{border-color:#255f75;box-shadow:0 6px 20px #17252f12}.edition:focus-visible{outline:3px solid #255f75;outline-offset:3px}
.cover{height:252px;padding:18px;box-sizing:border-box;background:#f3f4f5;display:flex;align-items:center;justify-content:center;border-bottom:1px solid #e9ebee}
.cover img{display:block;max-width:100%;max-height:100%;width:auto;height:auto;box-shadow:0 2px 7px #17252f20}.placeholder{color:#727c83;font-size:13px}
.description{padding:16px 18px 18px}.publication{font-size:18px;font-weight:650;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0 0 7px}
.date{font-size:13px;color:#68747c;margin:0 0 17px}.bottom{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:12px;color:#68747c}.open{color:#255f75;font-weight:650;font-size:13px}
@media(max-width:540px){.editions{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.cover{height:200px;padding:12px}.description{padding:12px}.publication{font-size:16px}.bottom{flex-wrap:wrap}.date{font-size:12px}}
"""

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

READER_CSS = """
.reader{--accent:#255f75;max-width:740px;margin:0 auto;font:13px system-ui,sans-serif;color:#26343d}
.toolbar{display:flex;align-items:center;justify-content:center;gap:4px;width:max-content;max-width:100%;margin:0 auto 12px;padding:5px 8px;background:#fff;border:1px solid #e3e7ea;border-radius:9px;box-sizing:border-box}
button{display:grid;place-items:center;width:30px;height:30px;background:transparent;border:0;border-radius:5px;color:#34434c;cursor:pointer;font:19px system-ui}
button:hover:not(:disabled){background:#edf3f5;color:var(--accent)}button:disabled{opacity:.25;cursor:default}button:focus-visible{outline:2px solid var(--accent)}
.page{min-width:52px;text-align:center;font-variant-numeric:tabular-nums}.zoom{min-width:40px;text-align:center;font-size:11px;font-variant-numeric:tabular-nums}.separator{width:1px;height:18px;background:#e3e7ea;margin:0 4px}
.stage{height:70vh;height:70dvh;max-height:780px;overflow:auto;background:#f3f4f5;border:1px solid #e7eaed;border-radius:10px;box-sizing:border-box}
.paper{display:flex;align-items:center;justify-content:center;min-width:100%;min-height:100%;box-sizing:border-box;padding:16px}
img{display:block;flex-shrink:0;max-width:none;box-shadow:0 2px 12px #17252f1c;background:white;object-fit:contain}
.reader-status{display:block;text-align:center;font-size:12px;color:#68747c;margin-top:4px}
.reader:fullscreen{max-width:none;width:100vw;height:100vh;background:#f3f4f5;padding:12px;box-sizing:border-box}.reader:fullscreen .stage{height:calc(100vh - 76px);max-height:none}
@media(max-width:540px){.toolbar{gap:1px;padding:4px}.separator{margin:0 2px}button{width:27px;height:28px}.stage{border-radius:6px}.paper{padding:10px}}
"""

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

gallery_component = st.components.v2.component("edicola_archive_gallery", html='<div class="editions" aria-label="Edizioni disponibili"></div>',
                                               css=GALLERY_CSS, js=GALLERY_JS, isolate_styles=True)
reader_component = st.components.v2.component("edicola_archive_reader", html=READER_HTML, css=READER_CSS, js=READER_JS, isolate_styles=True)
