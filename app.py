"""
app.py — Streamlit UI for the Aviation Chatbot
================================================
This file contains ONLY Streamlit page rendering + wiring to the LangGraph
agent. ALL tool logic now lives in two separate MCP servers, launched as
subprocesses by client/mcp_agent.py:

    servers/aviation_server/  — external API tools (flight status, live
                                 tracking, route search, weather, news,
                                 reliability stats, trip planning)
    servers/database_server/  — local PostgreSQL cache read tools

Run with:
    streamlit run app.py
"""

import re
import asyncio

import streamlit as st
from dotenv import load_dotenv

from client.mcp_agent import load_mcp_tools, build_agent
from client.callbacks import TimingCallbackHandler
from shared.embeddings import create_embedding
from shared.db.repositories.semantic_cache_repository import get_cached_response, save_to_cache

load_dotenv()

st.set_page_config(page_title="Aviation Chatbot", page_icon="✈️")
st.title("✈️ Aviation Chatbot")


# ── Agent (cached — built once per Streamlit session) ───────────────────────
@st.cache_resource(show_spinner="Connecting to MCP servers…")
def get_agent():
    tools = asyncio.run(load_mcp_tools())
    return build_agent(tools)


# ── Utility parsers for live-tracking UI widget ──────────────────────────────
def parse_tracking_progress(text: str) -> int | None:
    match = re.search(r"Journey Progress:\s*(\d+)%", text)
    return int(match.group(1)) if match else None


def parse_tracking_route(text: str) -> str | None:
    match = re.search(r"Route:\s*(\S+\s*[→>-]+\s*\S+)", text)
    return match.group(1) if match else None


# ── Session state ────────────────────────────────────────────────────────────
agent = get_agent()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    import uuid
    st.session_state.thread_id = str(uuid.uuid4())

# ── Render chat history ──────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            pct = parse_tracking_progress(msg["content"])
            if pct is not None:
                route = parse_tracking_route(msg["content"]) or ""
                st.caption(f"✈️ Journey progress {route}")
                st.progress(pct / 100)
            
            if "timings" in msg and msg["timings"]:
                with st.expander("⏱️ Execution Timings"):
                    for timing in msg["timings"]:
                        st.text(timing)

# ── New user input ───────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask about a flight or route…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                # Semantic Cache Intercept
                embedding = create_embedding(prompt)
                cached_reply = get_cached_response(embedding)

                if cached_reply:
                    reply = cached_reply
                    timing_handler = None
                    st.toast("⚡ Semantic Cache Hit!")
                    print(f"\n[CACHE HIT] Answer served from Semantic Cache for query: '{prompt}'")
                else:
                    print(f"\n[CACHE MISS] Querying LLM and Tools for: '{prompt}'")
                    timing_handler = TimingCallbackHandler()
                    config = {
                        "configurable": {"thread_id": st.session_state.thread_id},
                        "callbacks": [timing_handler]
                    }
                    response = asyncio.run(agent.ainvoke({"messages": [("user", prompt)]}, config))
                    reply = response["messages"][-1].content
                    
                    # Determine if it was a live query by checking the tools called
                    used_live_tools = False
                    live_tools = {
                        "get_flight_details", "track_flight_live", "get_flights_by_route",
                        "get_airport_weather", "search_aviation_news", "get_flight_reliability",
                        "get_flight_route_info", "plan_trip_itinerary"
                    }
                    
                    for msg in response["messages"]:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                if tc.get("name") in live_tools:
                                    used_live_tools = True
                                    break
                        if used_live_tools:
                            break
                    
                    if used_live_tools:
                        expires_in_hours = 1 / 60.0  # 1 minute
                        print(f"[CACHE STORED] Saved new response to Semantic Cache (Live Data, TTL=1min).")
                    else:
                        expires_in_hours = 30 * 24.0  # 30 days
                        print(f"[CACHE STORED] Saved new response to Semantic Cache (General Data, TTL=30days).")
                    
                    # Save new response to cache
                    save_to_cache(query=prompt, response=reply, embedding=embedding, expires_in_hours=expires_in_hours)
            except Exception as e:
                reply = f"Sorry, something went wrong: {e}"
                timing_handler = None
        st.markdown(reply)

        pct = parse_tracking_progress(reply)
        if pct is not None:
            route = parse_tracking_route(reply) or ""
            st.caption(f"✈️ Journey progress {route}")
            st.progress(pct / 100)

        timings = timing_handler.timings if timing_handler else []
        if timings:
            with st.expander("⏱️ Execution Timings"):
                for timing in timings:
                    st.text(timing)

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply,
        "timings": timings
    })
