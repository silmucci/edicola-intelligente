"""Contesto limitato per interpretare follow-up, mai come fonte documentale."""

from edicola.chat_data import bounded_context


def retrieval_query(question, context):
    previous = bounded_context(context)
    if not previous:
        return question
    # Risoluzione locale, senza una seconda chiamata LLM di riscrittura.
    topics = "\n".join(item["content"] for item in previous if item["role"] == "user")
    last_answer = next((item["content"][:400] for item in reversed(previous) if item["role"] == "assistant"), "")
    return f"Domande precedenti nella stessa conversazione:\n{topics}\nContesto tematico della risposta precedente:\n{last_answer}\nDomanda attuale: {question}"
