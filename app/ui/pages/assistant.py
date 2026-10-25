"""Assistant SmartGrid : conversation fondée sur le graphe (RAG), avec citation des éléments utilisés."""
import streamlit as st

from app.ai import chatbot, llm
from app.sparql.store import get_store
from app.ui import common

common.exiger_connexion()
store = get_store()
st.title("🤖 Assistant SmartGrid")
common.phrase("Posez vos questions en langage naturel : l'assistant cherche les faits dans le graphe puis vous répond en citant les éléments utilisés.")
if not llm.disponible():
    st.info("Mode sans IA générative : l'assistant répond avec des phrases automatiques. "
            "Ajoutez `ANTHROPIC_API_KEY` dans `.env` pour des réponses plus rédigées.")

if "chat" not in st.session_state:
    st.session_state["chat"] = [{"role": "assistant", "content": "Bonjour ! Je peux vous renseigner sur les bâtiments, les sources, "
                                 "les batteries, les nœuds et les utilisateurs. Que voulez-vous savoir ?", "sources": [], "sparql": ""}]

suggestions = ["Quelle est la consommation de ESPRIT ?", "Parle-moi de la Ferme solaire de Tunis",
               "Quels bâtiments sont alimentés par une source renouvelable ?", "Combien de batteries y a-t-il ?"]
cols = st.columns(len(suggestions))
choix = None
for c, s in zip(cols, suggestions):
    if c.button(s, key=f"sg_{s}", width="stretch"):
        choix = s

for m in st.session_state["chat"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("sources"):
            st.caption("Éléments utilisés : " + ", ".join(f"« {s['nom']} »" for s in m["sources"]))
        if m.get("sparql"):
            common.voir_sparql(m["sparql"])

saisie = st.chat_input("Votre question…") or choix
if saisie:
    st.session_state["chat"].append({"role": "user", "content": saisie})
    historique = [{"role": m["role"], "content": m["content"]} for m in st.session_state["chat"][:-1] if m["role"] in ("user", "assistant")]
    historique = [m for m in historique if m["role"] == "user" or True][-6:]
    # l'API exige un premier message « user »
    while historique and historique[0]["role"] != "user":
        historique.pop(0)
    r = chatbot.repondre(saisie, historique, store)
    st.session_state["chat"].append({"role": "assistant", "content": r["texte"], "sources": r["sources"], "sparql": r["sparql"]})
    st.rerun()

if st.button("🧹 Nouvelle conversation"):
    st.session_state.pop("chat", None)
    st.rerun()
