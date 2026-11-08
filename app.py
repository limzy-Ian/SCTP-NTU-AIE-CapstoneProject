"""Streamlit entry point for the read-only maintenance RAG prototype."""
import json
import os
import time

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from scripts.maintenance_rag import (
    ROOT, SYSTEM_PROMPT, input_refusal, load_sources, retrieve, validate_answer,
)


def show_evidence(sources):
    for source in sources:
        with st.expander(f"[{source['id']}] {source['title']}"):
            st.caption(source["location"])
            st.text(source["text"])
            filename = source.get("image")
            if filename and filename == os.path.basename(filename):
                image = ROOT / "data" / "images" / "nameplates" / filename
                if image.is_file():
                    st.image(str(image))


def main():
    load_dotenv(ROOT / ".env")
    st.set_page_config(page_title="Jurong Marine Maintenance", page_icon=":wrench:", layout="wide")
    st.title("Jurong Marine Maintenance")
    with st.sidebar:
        st.header("Sources")
        st.caption("MySQL / nameplate staging / SOPs")
        st.caption("Read-only prototype. OCR records require verification.")
        if st.button("Clear conversation", icon=":material/delete:"):
            st.session_state.messages = []
        st.metric("Session API tokens", st.session_state.get("tokens", 0))
        st.caption(f"Model: {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")
    if "messages" not in st.session_state:
        st.session_state.messages = []
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            show_evidence(message.get("sources", []))
    question = st.chat_input("Ask about a machine or safety procedure")
    if not question:
        return
    with st.chat_message("user"):
        st.markdown(question)
    history = [{"role": message["role"], "content": message["content"]}
               for message in st.session_state.messages[-6:]]
    st.session_state.messages.append({"role": "user", "content": question})
    sources, warnings, tokens = [], [], 0
    started = time.perf_counter()
    answer = input_refusal(question)
    with st.chat_message("assistant"):
        if answer is None:
            with st.spinner("Checking sources"):
                corpus, warnings = load_sources()
                retrieval_question = question
                if not any(character.isdigit() for character in question):
                    previous = next((item["content"] for item in reversed(history)
                                     if item["role"] == "user"), "")
                    retrieval_question = previous + " " + question
                sources = retrieve(retrieval_question, corpus)
                if not sources:
                    answer = "I could not find evidence to answer that question. Specify an asset tag or SOP topic."
                elif not os.getenv("OPENAI_API_KEY"):
                    answer = "The AI endpoint is not configured. Retrieved evidence is available below; no AI answer was generated."
                else:
                    try:
                        client = OpenAI(
                            api_key=os.environ["OPENAI_API_KEY"],
                            base_url=os.getenv("OPENAI_BASE_URL") or None,
                            timeout=30, max_retries=1,
                        )
                        evidence = json.dumps(sources, ensure_ascii=True)
                        response = client.chat.completions.create(
                            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                            temperature=0, max_tokens=700,
                            messages=[{"role": "system", "content": SYSTEM_PROMPT}]
                            + history + [{"role": "user", "content":
                                          f"Question: {question}\nSource availability warnings: {warnings}\nRetrieved evidence:\n{evidence}"}],
                        )
                        answer = validate_answer(response.choices[0].message.content or "", sources)
                        tokens = response.usage.total_tokens if response.usage else 0
                    except OpenAIError:
                        answer = "The AI endpoint is unavailable. I could not generate an answer; review the retrieved evidence below."
        for warning in warnings:
            st.warning(warning)
        st.markdown(answer)
        show_evidence(sources)
        st.caption(f"{len(sources)} sources / {time.perf_counter() - started:.1f}s / {tokens} API tokens")
    st.session_state.tokens = st.session_state.get("tokens", 0) + tokens
    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})


if __name__ == "__main__":
    main()