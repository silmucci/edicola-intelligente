"""Grafo locale cliccabile dei soli nodi/archi già validati; nessuna rete."""

import hashlib
import json
import streamlit as st

from edicola.design_tokens import COLORS, scoped_css
from edicola.map_presentation import GROUPS, node_captions
from edicola.map_story import story_focus

CSS = scoped_css("""
.viewport{max-width:100%;max-height:75vh;min-height:340px;overflow:auto;overscroll-behavior:contain;border:1px solid var(--edi-border);border-radius:var(--edi-radius);background:radial-gradient(circle at 20% 20%,var(--edi-surface),var(--edi-paper) 70%);font-family:var(--edi-sans);color:var(--edi-ink)}
.canvas{position:relative;margin:0 auto}.canvas svg{position:absolute;inset:0;overflow:visible;pointer-events:none}
.node{position:absolute;box-sizing:border-box;width:208px;padding:14px;border:1px solid var(--edi-border);border-radius:16px;color:var(--edi-ink);font:650 15px/1.4 var(--edi-sans);text-align:center;white-space:normal;overflow-wrap:anywhere;cursor:pointer;box-shadow:var(--edi-shadow);transition:transform .16s ease,box-shadow .16s ease,opacity .16s ease}
.node:hover{transform:translateY(-3px);box-shadow:0 10px 28px rgba(18,49,83,.13)}
.node.person{border-radius:32px}.node.article{border-left:4px solid #45916A}.node.source{border-left:4px solid #9CA3AF}.node.event,.node.proposal{border-left:4px solid var(--edi-accent)}
.node .kind{display:block;font-size:11px;font-weight:500;color:var(--edi-muted);margin-bottom:6px}.node.active{outline:3px solid var(--edi-primary);outline-offset:2px}.node:focus-visible{outline:3px solid var(--edi-accent);outline-offset:3px}
.edge-label{font:12px var(--edi-sans);fill:var(--edi-ink);paint-order:stroke;stroke:var(--edi-paper);stroke-width:5px;stroke-linejoin:round}
""")

JS = r"""
export default function({parentElement,data,setTriggerValue}){
 const canvas=parentElement.querySelector('.canvas');canvas.replaceChildren();
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
  return {...node,button,height:Math.max(80,button.offsetHeight)};
 });
 const byId=new Map(nodes.map(node=>[node.id,node])),neighbors=new Map(nodes.map(node=>[node.id,[]]));
 for(const edge of data.edges){neighbors.get(edge.from).push(edge.to);neighbors.get(edge.to).push(edge.from);}
 for(const node of nodes){node.button.style.opacity=!data.selected||node.id===data.selected||neighbors.get(data.selected)?.includes(node.id)?'1':'.45';}
 // Gerarchia delle relazioni: nucleo della vicenda, interventi, dettagli.
 // Ogni nodo mantiene gli archi originali; il layout non aggiunge fatti.
 const roots=[],seen=new Set(),children=new Map(nodes.map(n=>[n.id,[]]));
 const depth=new Map(),center=new Map();
 const preferred=byId.has(data.focus)?data.focus:nodes[0]?.id;
 const starts=[preferred,...nodes.map(n=>n.id).filter(id=>id!==preferred)].filter(Boolean);
 for(const root of starts){
  if(seen.has(root))continue;
  roots.push(root);
  const queue=[root];seen.add(root);depth.set(root,0);
  while(queue.length){
   const id=queue.shift();
   // I fatti e gli interventi precedono le menzioni secondarie.
   const next=[...(neighbors.get(id)||[])].sort((a,b)=>{
    const rank=x=>data.edges.some(e=>e.kind==='documented'&&
      (e.from===id&&e.to===x||e.to===id&&e.from===x))?0:1;
    return rank(a)-rank(b);
   });
   for(const other of next){
    if(seen.has(other))continue;
    seen.add(other);depth.set(other,depth.get(id)+1);
    children.get(id).push(other);queue.push(other);
   }
  }
 }
 // Un sottoalbero occupa lo spazio dei propri figli: niente enormi archi
 // che scorrono per tutta l'altezza lungo i bordi del canvas.
 const nodeWidth=208,stepX=250;
 let leaves=0;
 const place=id=>{
  const kids=children.get(id)||[];
  if(!kids.length){const x=144+leaves++*stepX;center.set(id,x);return x;}
  const centers=kids.map(place);
  const x=(centers[0]+centers[centers.length-1])/2;
  center.set(id,x);return x;
 };
 for(const root of roots){place(root);leaves++;}
 const width=Math.max(380,Math.round(80+Math.max(1,leaves-1)*stepX));
 const heights=new Map();
 for(const node of nodes){
  node.row=depth.get(node.id)||0;
  heights.set(node.row,Math.max(heights.get(node.row)||0,node.height));
 }
 const maxDepth=Math.max(0,...nodes.map(n=>n.row));
 const layerY=new Map();let top=28;
 const layerGap=144;
 for(let i=0;i<=maxDepth;i++){layerY.set(i,top);top+=(heights.get(i)||80)+layerGap;}
 for(const node of nodes){
  node.x=Math.round(center.get(node.id)-nodeWidth/2);
  node.y=layerY.get(node.row);
  node.button.style.left=node.x+'px';node.button.style.top=node.y+'px';
 }
 const height=Math.max(200,top-layerGap+16);
 canvas.style.width=width+'px';canvas.style.height=height+'px';
 svg.setAttribute('width',width);svg.setAttribute('height',height);
 for(const [index,edge] of data.edges.entries()){
  const a=byId.get(edge.from),b=byId.get(edge.to),down=a.row<b.row,same=a.row===b.row;
  let x1=a.x+104,y1=down?a.y+a.height:a.y,x2=b.x+104,y2=down?b.y:b.y+b.height,path,labelX,labelY,rotate=false;
  if(same){x1=a.x+(a.x<b.x?208:0);x2=b.x+(a.x<b.x?0:208);y1=a.y+a.height/2;y2=b.y+b.height/2;path=`M${x1},${y1} L${x2},${y2}`;labelX=(x1+x2)/2;labelY=Math.min(y1,y2)-12;}
  else if(Math.abs(a.row-b.row)===1){const mid=(y1+y2)/2;path=`M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`;labelX=(x1+x2)/2;labelY=mid-8;}
  else {const mid=(y1+y2)/2;path=`M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`;labelX=(x1+x2)/2;labelY=mid-8;}
  const line=make('path',{d:path,fill:'none',stroke:data.primary,'stroke-width':2.4,'stroke-linejoin':'round'});
  const emphasized=!data.selected||edge.from===data.selected||edge.to===data.selected;
  line.setAttribute('opacity',emphasized?'1':'.2');
  if(edge.kind==='documented'||edge.kind==='mention'||edge.kind==='contextual')line.setAttribute('marker-end','url(#arrow)');
  if(edge.kind==='mention')line.setAttribute('stroke-dasharray','2 5');
  else if(edge.kind!=='documented')line.setAttribute('stroke-dasharray','6 5');
  const original=make('title');original.textContent=edge.label;line.append(original);svg.append(line);
  const label=make('text',{x:labelX,y:labelY,'text-anchor':'middle',class:'edge-label'});
  label.setAttribute('opacity',emphasized?'1':'.25');
  if(rotate){label.setAttribute('transform',`rotate(-90 ${labelX} ${labelY})`);label.textContent=edge.label;svg.append(label);continue;}
  const words=edge.label.split(/\s+/),lines=[];let current='';
  for(const word of words){if(current.length+word.length>24&&current){lines.push(current);current=word;}else current+=(current?' ':'')+word;}if(current)lines.push(current);
  lines.forEach((text,i)=>{const span=make('tspan',{x:labelX,dy:i?15:0});span.textContent=text;label.append(span);});svg.append(label);
 }
}
"""

graph_component = st.components.v2.component("edicola_concept_graph", html='<div class="viewport" tabindex="0" role="region" aria-label="Mappa: seleziona un concetto o scorri per esplorare"><div class="canvas"></div></div>',
                                           css=CSS, js=JS, isolate_styles=True)


def render_graph(data, *, topic, selected, on_select):
    captions = node_captions(data["nodes"])
    payload = {"nodes": [{"id": n["id"], "label": captions[n["id"]], "kind": n["kind"],
                          "type": GROUPS[n["kind"]][0], "color": GROUPS[n["kind"]][3]} for n in data["nodes"]],
               "edges": [{"from": e["from_id"], "to": e["to_id"], "label": e.get("topic") or e["label"], "kind": e["kind"]} for e in data["edges"]]}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    key = "knowledge_graph_" + identity
    def choose():
        index = st.session_state.get(key, {}).get("selected")
        if type(index) is int and 0 <= index < len(data["nodes"]):
            on_select(data["nodes"][index]["id"])
    graph_component(data={**payload, "selected": selected, "focus": story_focus(data, topic), "primary": COLORS["primary"]}, key=key, on_selected_change=choose)
