"""Token editoriali condivisi dai componenti locali; nessun font o asset remoto."""

COLORS = dict(paper="#FFFFFF", ink="#082654", primary="#0866D9", accent="#E51B2B",
              surface="#F2F7FD", border="#E2E8F0", muted="#536782")
TOKENS = {**COLORS, "sans": "system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
          "serif": "Georgia,'Times New Roman',serif", "radius": "16px", "space": "20px",
          "shadow": "0 6px 24px #08265408", "focus": "0 0 0 3px #0866D940"}
CSS_VARS = ":host{display:block;min-width:0;max-width:100%;" + ";".join(f"--edi-{key}:{value}" for key, value in TOKENS.items()) + "}"

# Solo classi applicative esplicite: non modifica il DOM o i widget Streamlit.
EDITORIAL_CSS = """
.edi-brand,.edi-section{box-sizing:border-box;color:var(--edi-ink);font-family:var(--edi-sans)}
.edi-brand{display:flex;align-items:center;gap:14px;padding:12px 0 18px;max-width:100%}
.edi-brand svg{width:48px;height:48px;flex-shrink:0;color:var(--edi-accent)}
.edi-brand h1{font:700 clamp(22px,2.4vw,34px)/1.12 var(--edi-serif);letter-spacing:-.035em;margin:0}
.edi-brand strong{color:var(--edi-primary)}.edi-brand p{color:var(--edi-muted);font-size:14px;line-height:1.5;margin:6px 0 0}
.edi-section{margin:20px 0 26px;max-width:100%}
.edi-section .eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--edi-muted);display:flex;align-items:center;gap:12px;margin-bottom:12px}
.edi-section .eyebrow:before{content:'';height:3px;width:28px;background:var(--edi-accent)}
.edi-section h2{font:700 clamp(28px,4vw,48px)/1.12 var(--edi-serif);letter-spacing:-.03em;margin:0 0 12px;overflow-wrap:anywhere}
.edi-section p{font-size:16px;line-height:1.6;color:var(--edi-muted);margin:0;max-width:760px}
@media(max-width:768px){.edi-brand{gap:10px}.edi-brand svg{width:38px;height:38px}.edi-section{margin:14px 0 20px}}
@media(max-width:430px){.edi-brand p{font-size:12px}.edi-section p{font-size:15px}.edi-brand h1{font-size:23px}}
@media(prefers-reduced-motion:reduce){.edi-brand,.edi-section{scroll-behavior:auto}}
"""


def scoped_css(css):
    return CSS_VARS + css


def page_css():
    # st.html è privo di shadow root; le variabili restano sulle nostre sole classi.
    variables = ";".join(f"--edi-{key}:{value}" for key, value in TOKENS.items())
    return f".edi-brand,.edi-section{{{variables}}}" + EDITORIAL_CSS
