"""Grounded chat page: ask questions answered only from the fetched HKO data."""

import streamlit as st

from streamlit_weather import data, llm
from streamlit_weather import transform as tf
from streamlit_weather.helpers import page_icon

st.set_page_config(
    page_title="Ask About the Forecast · Hong Kong Weather Dashboard",
    page_icon=page_icon(),
    layout="wide",
)

with st.spinner("Loading the latest HKO data…"):
    weather = data.load()

if weather["is_fallback"]:
    st.info(data.FALLBACK_NOTICE)

st.title("💬 Ask About the Forecast")
st.caption("Answers are grounded in the forecast and warning data the app fetched.")

retrieved_context = tf.build_context(weather["forecast_df"], weather["warning_summaries"])

# Replay history. Only the most recent reply gets a context expander so the
# transcript stays scannable; older replies were grounded in the same snapshot.
if "messages" not in st.session_state:
    st.session_state.messages = []

last_assistant_index = max(
    (i for i, m in enumerate(st.session_state.messages) if m["role"] == "assistant"),
    default=None,
)
for index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if index == last_assistant_index and not message.get("error"):
            with st.expander("Show retrieved context"):
                st.code(message.get("context", retrieved_context), language="json")

if prompt := st.chat_input("e.g. Which day has the highest chance of rain?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            reply, is_error = llm.answer(prompt, retrieved_context, st.session_state.messages[:-1])
        st.markdown(reply)
        if not is_error:
            with st.expander("Show retrieved context"):
                st.code(retrieved_context, language="json")

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": reply,
            "context": retrieved_context,
            "error": is_error,
        }
    )
