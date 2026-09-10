"""
client/mcp_agent.py
=====================
Builds the LangGraph agent used by app.py. The agent talks to BOTH MCP
servers (aviation_server, database_server) as tools, loaded over stdio via
langchain-mcp-adapters' MultiServerMCPClient — each server runs as its own
subprocess, exactly like it would under Claude Desktop / any other MCP host.

This file replaces the old monolithic `build_agent()` in app.py, which
imported every @tool function directly in-process. Now the two toolsets are
fully decoupled processes talking MCP.
"""

import datetime
import sys
from pathlib import Path

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, AnyMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langgraph.types import Command
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import TypedDict, Annotated, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

MCP_SERVERS = {
    "aviation": {
        "command": PYTHON,
        "args": ["-m", "servers.aviation_server.server"],
        "cwd": str(PROJECT_ROOT),
        "transport": "stdio",
    },
    "database": {
        "command": PYTHON,
        "args": ["-m", "servers.database_server.server"],
        "cwd": str(PROJECT_ROOT),
        "transport": "stdio",
    },
}

SYSTEM_PROMPT = (
    "You are a friendly and helpful aviation assistant. Today's date is {today}.\n\n"
    
    "## CONTEXT & MEMORY\n"
    "When you learn important flight details (flight number, origin, destination, date), ALWAYS call `update_memory` to save them. "
    "Check the CURRENT CONTEXT section if the user refers to 'that flight' or 'the destination' implicitly.\n\n"

    "## DATABASE-FIRST RULE (VERY IMPORTANT)\n"
    "Always call search_database FIRST (or the matching get_*_cached / get_*_info tool) for:\n"
    "  - Airport info (query_type='airport', query=city/IATA/name)\n"
    "  - Airline info (query_type='airline', query=name/IATA)\n"
    "  - Flight status (query_type='flight', flight_number=..., date=...)\n"
    "  - Route/flight search (query_type='route', origin=IATA, destination=IATA, date=...)\n"
    "If it returns found=True AND fresh=True, use that data to answer the user.\n"
    "Only call get_flight_details or get_flights_by_route (aviation server) if the database "
    "tool returns found=False OR fresh=False.\n\n"

    "## TOOL GUIDE\n"
    "- search_database / get_airport_info / get_airline_info / get_flight_status_cached / get_route_cached:\n"
    "  Local PostgreSQL cache reads — ALWAYS try these first, they're instant and free.\n"
    "- get_flight_details:  Live lookup (AeroDataBox, falling back to Aviationstack). Use only on a cache miss/stale result.\n"
    "- get_flights_by_route: Live route/price search via Google Flights. Use only on a cache miss/stale result.\n"
    "- track_flight_live:   Use when the user asks to TRACK or see the LIVE POSITION of a flight.\n"
    "- search_aviation_news: Use for ACCIDENTS, INCIDENTS, NEWS, closures, or real-world events.\n"
    "- get_flight_reliability: Use for 'How reliable is X?' / on-time stats.\n"
    "- get_flight_route_info:  Use for 'Where does X usually fly?'.\n"
    "- get_airport_weather: CURRENT weather/conditions only — never for a future flight date.\n"
    "- plan_trip_itinerary: Trip/connection planning. Present 3-4 options and ask if the user wants adjustments.\n\n"

    "## TIME DISPLAY (CRITICAL)\n"
    "Tool results are already formatted in the LOCAL timezone of each airport. Use those exact "
    "date-time strings as-is. Do not re-calculate, re-convert, or drop the date portion, and never "
    "convert one airport's time into the other airport's timezone.\n\n"

    "## DELAY RULE (CRITICAL)\n"
    "Never invent or guess delay values. Only state a delay when a tool gives BOTH a scheduled and "
    "an actual/predicted time. If a tool says 'No delay info' or 'N/A', say exactly that.\n\n"

    "## DATE RULE\n"
    "Only pass a 'date' argument if the user explicitly mentioned one. Never invent or guess a date.\n\n"

    "## MULTI-ROUTE FLIGHTS\n"
    "If a tool returns multiple routes/occurrences for a flight, present ALL of them. Do not ask the user to choose.\n\n"

    "## DISPLAY & FORMATTING RULES\n"
    "1. AIRPORT CODES: always show 'IATA (City)', e.g. 'DEL (Delhi)'.\n"
    "2. Keep tables spacious; use bulleted lists for multi-leg itineraries instead of cramming a table cell.\n"
    "3. No raw HTML tags (e.g. <br>) in markdown output.\n\n"

    "## FABRICATION RULE\n"
    "NEVER fabricate flight data. If a tool fails or returns FLIGHT_DATA_UNAVAILABLE, say so honestly."
)

class AviationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    flight_number: Optional[str]
    departure_airport: Optional[str]
    arrival_airport: Optional[str]
    travel_date: Optional[str]

@tool
def update_memory(
    flight_number: str = None, 
    departure_airport: str = None, 
    arrival_airport: str = None, 
    travel_date: str = None
):
    """Use this tool to save important flight details (flight number, route, date) into memory for later reference."""
    updates = {}
    if flight_number: updates["flight_number"] = flight_number
    if departure_airport: updates["departure_airport"] = departure_airport
    if arrival_airport: updates["arrival_airport"] = arrival_airport
    if travel_date: updates["travel_date"] = travel_date
    return Command(update=updates)


async def load_mcp_tools():
    """Connect to both MCP servers and return their combined tool list."""
    client = MultiServerMCPClient(MCP_SERVERS)
    return await client.get_tools()


def build_agent(tools):
    """Build the LangGraph agent graph given an already-loaded tool list."""
    
    # Add our local memory tool to the list of tools
    all_tools = tools + [update_memory]
    
    llm = ChatGroq(model="openai/gpt-oss-20b", temperature=0)
    llm_with_tools = llm.bind_tools(all_tools)

    system_prompt_base = SYSTEM_PROMPT.format(today=datetime.datetime.now().strftime("%Y-%m-%d"))

    def call_model(state: AviationState):
        context_str = []
        if state.get("flight_number"): context_str.append(f"Flight: {state['flight_number']}")
        if state.get("departure_airport"): context_str.append(f"Origin: {state['departure_airport']}")
        if state.get("arrival_airport"): context_str.append(f"Destination: {state['arrival_airport']}")
        if state.get("travel_date"): context_str.append(f"Date: {state['travel_date']}")
        
        ctx = " | ".join(context_str) if context_str else "None"
        system_prompt = system_prompt_base + f"\n\nCURRENT CONTEXT: {ctx}"
        
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AviationState):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    workflow = StateGraph(AviationState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(all_tools))
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, ["tools", END])
    workflow.add_edge("tools", "agent")

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
