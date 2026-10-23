"""Download/audio personali nel WebSocket della sessione, senza URL media pubblici."""

import base64

import streamlit as st

PRIVATE_MEDIA_JS = """
export default function({parentElement,data}) {
  const root=parentElement.querySelector('.private-media');
  const audio=root.querySelector('audio'), button=root.querySelector('button');
  const bytes=Uint8Array.from(atob(data.bytes), c=>c.charCodeAt(0));
  const url=URL.createObjectURL(new Blob([bytes],{type:data.mime}));
  audio.hidden=!data.play; if(data.play) audio.src=url;
  button.textContent=data.label;
  button.onclick=()=>{const a=document.createElement('a');a.href=url;a.download=data.filename;a.click();};
  return ()=>{audio.pause();audio.removeAttribute('src');URL.revokeObjectURL(url);};
}
"""

_media = st.components.v2.component("edicola_private_media",
    html='<div class="private-media"><audio controls aria-label="Podcast personale" hidden></audio><button type="button"></button></div>',
    css=".private-media{font-family:system-ui,sans-serif;max-width:620px}.private-media audio{width:100%;margin:8px 0 16px}.private-media button{background:white;color:#255f75;border:1px solid #d4dde1;border-radius:8px;padding:10px 16px;font:inherit;cursor:pointer}.private-media button:focus-visible{outline:3px solid #255f75;outline-offset:2px}",
    js=PRIVATE_MEDIA_JS, isolate_styles=True)


def private_download(data, *, label, filename, mime, key, play=False):
    if mime not in {"application/json", "audio/wav"} or any(c in filename for c in "/\\:\0"):
        raise ValueError("Formato di download personale non consentito.")
    payload = data.encode("utf-8") if isinstance(data, str) else data
    _media(data={"bytes": base64.b64encode(payload).decode("ascii"), "label": label,
                 "filename": filename, "mime": mime, "play": play}, key=key)
