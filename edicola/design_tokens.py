"""Token editoriali condivisi dai componenti locali; nessun font o asset remoto."""

COLORS = dict(paper="#FFFFFF", ink="#1C2938", primary="#275D9B", accent="#B26A55",
              surface="#F5F7FA", border="#E3E8ED", muted="#5E6B78")
TOKENS = {**COLORS, "sans": "system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
          "serif": "Georgia,'Times New Roman',serif", "radius": "12px", "space": "20px",
          "shadow": "0 2px 14px #1C293808", "focus": "0 0 0 3px #275D9B40"}
CSS_VARS = ":host{display:block;min-width:0;max-width:100%;" + ";".join(f"--edi-{key}:{value}" for key, value in TOKENS.items()) + "}"

# Solo classi applicative esplicite: non modifica il DOM o i widget Streamlit.
EDITORIAL_CSS = """
.edi-brand,.edi-section{box-sizing:border-box;color:var(--edi-ink);font-family:var(--edi-sans)}
.edi-brand{display:flex;align-items:center;padding:5px 0 14px;max-width:100%;min-width:0}.edi-brand>div{min-width:0}.edi-brand h1{overflow-wrap:anywhere}
.edi-brand h1{font:700 clamp(22px,2.2vw,29px)/1.15 var(--edi-serif);letter-spacing:-.035em;margin:0}
.edi-brand strong{color:var(--edi-primary);font-weight:700}.edi-brand p{color:var(--edi-muted);font-size:12px;line-height:1.45;margin:4px 0 0}
.edi-section{margin:23px 0 23px;max-width:100%}
.edi-section .eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--edi-muted);display:flex;align-items:center;gap:12px;margin-bottom:12px}
.edi-section .eyebrow:before{content:'';height:3px;width:28px;background:var(--edi-accent)}
.edi-section h2{font:700 clamp(27px,3.6vw,40px)/1.14 var(--edi-serif);letter-spacing:-.03em;margin:0 0 9px;overflow-wrap:anywhere}
.edi-section p{font-size:16px;line-height:1.6;color:var(--edi-muted);margin:0;max-width:760px}
@media(max-width:768px){.edi-section{margin:16px 0 18px}}
@media(max-width:430px){.edi-brand p{font-size:11px}.edi-section p{font-size:15px}.edi-brand h1{font-size:22px}}
@media(max-width:600px){.edi-brand p{display:none}.edi-brand h1{font-size:20px}.edi-brand{padding:4px 0 9px}}
@media(prefers-reduced-motion:reduce){.edi-brand,.edi-section{scroll-behavior:auto}}
"""


def scoped_css(css):
    return CSS_VARS + css


def page_css():
    # st.html è privo di shadow root; le variabili restano sulle nostre sole classi.
    variables = ";".join(f"--edi-{key}:{value}" for key, value in TOKENS.items())
    return f".edi-brand,.edi-section{{{variables}}}" + EDITORIAL_CSS


// La shell Streamlit non e parte del contenuto editoriale. Questi selettori
// sono isolati dal CSS dei componenti v2: possono richiedere manutenzione
// quando cambia la versione di Streamlit. Non toccare dialoghi o controlli.
APP_SHELL_CSS = """
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stAppDeployButton"],
#MainMenu,footer[data-testid="stFooter"]{display:none!important}
[data-testid="stHeader"]{height:0!important;min-height:0!important;background:transparent!important}
[data-testid="stMainBlockContainer"]{max-width:1280px;padding:20px 32px 64px}
@media(max-width:768px){
  [data-testid="stMainBlockContainer"]{padding:12px 18px 44px}
}
@media(max-width:430px){
  [data-testid="stMainBlockContainer"]{padding:10px 12px 36px}
}
"""


def app_shell_css():
    """CSS della sola cornice app: non modifica widget, dati o componenti."""
    return APP_SHELL_CSS
