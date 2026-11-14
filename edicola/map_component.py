"""Grafo locale cliccabile dei soli nodi/archi già validati; nessuna rete."""

import hashlib
import json
import streamlit as st

from edicola.design_tokens import COLORS, scoped_css
from edicola.map_presentation import GROUPS, node_captions
from edicola.map_story import story_focus

CSS = scoped_css("""
.viewport{width:100%;max-width:100%;min-height:240px;overflow:visible;border:0;border-radius:0;background:transparent;font-family:var(--edi-sans);color:var(--edi-ink);box-sizing:border-box}
.canvas{position:relative;width:100%;margin:0 auto}.canvas svg{position:absolute;inset:0;overflow:visible;pointer-events:none}.graph-fallback{padding:40px 18px;text-align:center;color:var(--edi-muted);font:14px/1.5 var(--edi-sans)}
.node{position:absolute;box-sizing:border-box;width:250px;padding:14px;border:1px solid var(--edi-border);border-radius:16px;color:var(--edi-ink);font:650 15px/1.4 var(--edi-sans);text-align:center;white-space:normal;overflow-wrap:anywhere;cursor:pointer;box-shadow:var(--edi-shadow);transition:transform .16s ease,box-shadow .16s ease,opacity .16s ease}
.node:hover{transform:translateY(-3px);box-shadow:0 10px 28px rgba(18,49,83,.13)}
.node.person{border-radius:32px}.node.article{border-left:4px solid #45916A}.node.source{border-left:4px solid #9CA3AF}.node.event,.node.proposal{border-left:4px solid var(--edi-accent)}
.node .kind{display:block;font-size:11px;font-weight:500;color:var(--edi-muted);margin-bottom:6px}.node.active{outline:3px solid var(--edi-primary);outline-offset:2px}.node:focus-visible{outline:3px solid var(--edi-accent);outline-offset:3px}
.edge-label{font:12px var(--edi-sans);fill:var(--edi-ink);paint-order:stroke;stroke:var(--edi-paper);stroke-width:5px;stroke-linejoin:round}
@media(max-width:600px){.node{padding:11px;font-size:13px}.edge-label{font-size:11px}}
""")

DIRECTIONAL_EDGE_KINDS = frozenset({"documented", "mention"})


def is_directional_edge(edge):
    """Solo azioni verificate e menzioni della fonte hanno una freccia."""
    return edge.get("kind") in DIRECTIONAL_EDGE_KINDS


JS = r"""
export default function({parentElement,data,setTriggerValue}){
 const viewport=parentElement.querySelector('.viewport');
 const canvas=viewport.querySelector('.canvas'),fallback=viewport.querySelector('.graph-fallback');
 fallback.hidden=false;canvas.replaceChildren();
 if(parentElement.__ediGraphObserver)parentElement.__ediGraphObserver.disconnect();
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');canvas.append(svg);
 const make=(tag,attrs)=>{const el=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs||{}))el.setAttribute(key,value);return el;};
 const defs=make('defs'),marker=make('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});
 marker.append(make('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:data.primary}));defs.append(marker);svg.append(defs);
 const nodes=data.nodes.map((node,index)=>{
  const button=document.createElement('button');button.type='button';button.className='node '+node.kind;button.style.backgroundColor=node.color;
  const kind=document.createElement('span');kind.className='kind';kind.textContent=node.type;
  const title=document.createElement('span');title.textContent=node.label;button.append(kind,title);
  button.classList.toggle('active',node.id===(data.selected||data.focus));button.setAttribute('aria-pressed',String(node.id===data.selected));
  button.setAttribute('aria-label',node.label+': apri collegamenti e fonti');button.onclick=()=>setTriggerValue('selected',index);canvas.append(button);
  return {...node,button,height:80};
 });
 const byId=new Map(nodes.map(node=>[node.id,node])),neighbors=new Map(nodes.map(node=>[node.id,[]]));
 // Relazioni che non hanno entrambe le estremità visualizzate non possono
 // determinare le posizioni. Le prove originali non sono modificate.
 const visibleEdges=data.edges.filter(edge=>byId.has(edge.from)&&byId.has(edge.to));
 for(const edge of visibleEdges){neighbors.get(edge.from).push(edge.to);neighbors.get(edge.to).push(edge.from);}
 for(const node of nodes){node.button.style.opacity=!data.selected||node.id===data.selected||neighbors.get(data.selected)?.includes(node.id)?'1':'.45';}
 const preferred=byId.has(data.focus)?data.focus:nodes[0]?.id;
 const starts=[preferred,...nodes.map(n=>n.id).filter(id=>id!==preferred)].filter(Boolean);
 // L'attenzione editoriale evidenzia un nodo, ma non determina l'ordine
 // dei fatti. L'origine di un arco documentato deve precedere il suo oggetto.
 function directedLevels(component){
  const membership=new Set(component);
  const incoming=new Map(component.map(id=>[id,0]));
  const outgoing=new Map(component.map(id=>[id,0]));
  const facts=visibleEdges.filter(e=>e.directed&&membership.has(e.from)&&membership.has(e.to));
  for(const edge of facts){
   incoming.set(edge.to,incoming.get(edge.to)+1);
   outgoing.set(edge.from,outgoing.get(edge.from)+1);
  }
  const origins=component.filter(id=>outgoing.get(id)>0&&incoming.get(id)===0);
  const seeds=origins.length?origins:[membership.has(preferred)?preferred:component[0]];
  const depth=new Map(seeds.map(id=>[id,0]));
  const queue=[...seeds];
  while(queue.length){
   const id=queue.shift();
   for(const other of neighbors.get(id)){
    if(!membership.has(other)||depth.has(other))continue;
    depth.set(other,depth.get(id)+1);queue.push(other);
   }
  }
  for(const id of component)if(!depth.has(id))depth.set(id,0);
  // Se il grafo diretto è aciclico, impone una lettura dall'alto in basso
  // per TUTTE le frecce fattuali, anche in presenza di legami contestuali.
  const degree=new Map(component.map(id=>[id,0]));
  const forward=new Map(component.map(id=>[id,[]]));
  for(const edge of facts){
   degree.set(edge.to,degree.get(edge.to)+1);
   forward.get(edge.from).push(edge.to);
  }
  const available=component.filter(id=>degree.get(id)===0);
  const ordered=[];
  while(available.length){
   const id=available.shift();ordered.push(id);
   for(const target of forward.get(id)){
    degree.set(target,degree.get(target)-1);
    if(degree.get(target)===0)available.push(target);
   }
  }
  if(ordered.length===component.length){
   for(const id of ordered){
    for(const target of forward.get(id)){
     depth.set(target,Math.max(depth.get(target),depth.get(id)+1));
    }
   }
  }
  return depth;
 }
 let lastWidth=0;
 function layout(){
  // Ogni componente della mappa scorre nel normale documento. Niente
  // canvas esteso oltre lo schermo né scrollbars annidate.
  const width=Math.max(280,Math.round(viewport.getBoundingClientRect().width||parentElement.clientWidth||900));
  const gutter=20,spacing=30;
  const nodeWidth=Math.min(250,width-2*gutter);
  const columns=Math.max(1,Math.min(4,Math.floor((width-2*gutter+spacing)/(nodeWidth+spacing))));
  for(const node of nodes){
   node.button.style.width=nodeWidth+'px';
   node.height=Math.max(80,node.button.offsetHeight);
  }
  let top=24;
  const seen=new Set();
  for(const root of starts){
   if(seen.has(root))continue;
   const component=[],queue=[root];seen.add(root);
   while(queue.length){
    const id=queue.shift();component.push(id);
    for(const other of neighbors.get(id)){
     if(seen.has(other))continue;
     seen.add(other);queue.push(other);
    }
   }
   const levels=[],depths=directedLevels(component);
   for(const id of component){
    const depth=depths.get(id);
    (levels[depth]||(levels[depth]=[])).push(byId.get(id));
   }
   for(const level of levels){
    for(let offset=0;offset<level.length;offset+=columns){
     const group=level.slice(offset,offset+columns);
     const groupWidth=group.length*nodeWidth+(group.length-1)*spacing;
     // Il gruppo utilizza davvero la pagina: se c'è spazio, i fratelli
     // si distribuiscono orizzontalmente, senza creare scroll interno.
     const available=width-2*gutter;
     const stretch=group.length>1?Math.min(
      available,groupWidth+(group.length-1)*Math.min(150,Math.max(0,(available-groupWidth)/2))
     ):groupWidth;
     const left=Math.max(gutter,(width-stretch)/2);
     const step=group.length>1?(stretch-nodeWidth)/(group.length-1):0;
     for(const [index,node] of group.entries()){
      node.x=Math.round(left+index*step);
      node.y=Math.round(top);
      node.button.style.left=node.x+'px';
      node.button.style.top=node.y+'px';
     }
     top+=Math.max(...group.map(n=>n.height))+
          (offset+columns<level.length?42:76);
    }
   }
   top+=12;
  }
  const height=Math.max(240,top-44);
  canvas.style.height=height+'px';canvas.style.width='100%';
  svg.replaceChildren(defs);
  svg.setAttribute('width',width);svg.setAttribute('height',height);
  for(const edge of visibleEdges){
   const a=byId.get(edge.from),b=byId.get(edge.to);
   const aBefore=a.y+a.height<=b.y,bBefore=b.y+b.height<=a.y;
   let x1,y1,x2,y2,path,labelX,labelY;
   if(!aBefore&&!bBefore){
    x1=a.x+(a.x<b.x?nodeWidth:0);x2=b.x+(a.x<b.x?0:nodeWidth);
    y1=a.y+a.height/2;y2=b.y+b.height/2;
    path='M'+x1+','+y1+' L'+x2+','+y2;
    labelX=(x1+x2)/2;labelY=Math.min(y1,y2)-12;
   }else{
    x1=a.x+nodeWidth/2;y1=aBefore?a.y+a.height:a.y;
    x2=b.x+nodeWidth/2;y2=aBefore?b.y:b.y+b.height;
    const mid=(y1+y2)/2;
    path='M'+x1+','+y1+' C'+x1+','+mid+' '+x2+','+mid+' '+x2+','+y2;
    labelX=(x1+x2)/2;labelY=mid-8;
   }
   const line=make('path',{d:path,fill:'none',stroke:data.primary,'stroke-width':2.3,'stroke-linejoin':'round'});
   const emphasized=!data.selected||edge.from===data.selected||edge.to===data.selected;
   line.setAttribute('opacity',emphasized?'1':'.2');
   if(edge.directed)line.setAttribute('marker-end','url(#arrow)');
   if(edge.kind==='mention')line.setAttribute('stroke-dasharray','2 5');
   else if(edge.kind!=='documented')line.setAttribute('stroke-dasharray','6 5');
   const original=make('title');original.textContent=edge.label;line.append(original);svg.append(line);
   const label=make('text',{x:labelX,y:labelY,'text-anchor':'middle',class:'edge-label'});
   label.setAttribute('opacity',emphasized?'1':'.25');
   const words=edge.label.split(/\s+/),lines=[];let current='';
   for(const word of words){
    if(current.length+word.length>24&&current){lines.push(current);current=word;}
    else current+=(current?' ':'')+word;
   }
   if(current)lines.push(current);
   lines.forEach((text,i)=>{const span=make('tspan',{x:labelX,dy:i?15:0});span.textContent=text;label.append(span);});
   svg.append(label);
  }
 }
 function safeLayout(){
  try{layout();fallback.hidden=true;return true;}
  catch(error){fallback.hidden=false;return false;}
 }
 safeLayout();
 if(typeof requestAnimationFrame==='function'){
  requestAnimationFrame(()=>{
   const width=Math.round(viewport.getBoundingClientRect().width);
   if(width>0&&width!==lastWidth){lastWidth=width;safeLayout();}
  });
 }
 if(typeof ResizeObserver!=='undefined'){
  lastWidth=Math.round(viewport.getBoundingClientRect().width);
  const observer=new ResizeObserver(()=>{
   const width=Math.round(viewport.getBoundingClientRect().width);
   if(width>0&&width!==lastWidth){lastWidth=width;safeLayout();}
  });
  observer.observe(viewport);
  parentElement.__ediGraphObserver=observer;
 }
}
"""

graph_component = st.components.v2.component("edicola_concept_graph", html='<div class="viewport" tabindex="0" role="region" aria-label="Mappa: seleziona un concetto per esplorare relazioni e fonti"><div class="canvas"></div><p class="graph-fallback">La mappa non è visualizzabile. Puoi consultare i fatti documentati qui sotto.</p></div>',
                                           css=CSS, js=JS, isolate_styles=True)


def render_graph(data, *, topic, selected, on_select):
    captions = node_captions(data["nodes"])
    payload = {"nodes": [{"id": n["id"], "label": captions[n["id"]], "kind": n["kind"],
                          "type": GROUPS[n["kind"]][0], "color": GROUPS[n["kind"]][3]} for n in data["nodes"]],
               "edges": [{"from": e["from_id"], "to": e["to_id"], "label": e.get("topic") or e["label"],
                           "kind": e["kind"], "directed": is_directional_edge(e)} for e in data["edges"]]}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    key = "knowledge_graph_" + identity
    def choose():
        index = st.session_state.get(key, {}).get("selected")
        if type(index) is int and 0 <= index < len(data["nodes"]):
            on_select(data["nodes"][index]["id"])
    graph_component(data={**payload, "selected": selected, "focus": story_focus(data, topic), "primary": COLORS["primary"]}, key=key, on_selected_change=choose)
