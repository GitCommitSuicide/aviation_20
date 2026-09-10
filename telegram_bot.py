import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from client.mcp_agent import load_mcp_tools, build_agent
from shared.embeddings import create_embedding
from shared.db.repositories.semantic_cache_repository import get_cached_response, save_to_cache

# Load environment variables
load_dotenv()

# Global variable to hold the agent
agent = None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await update.message.reply_text(
        "✈️ Welcome to the Aviation Chatbot! Ask me about flights, routes, weather, or aviation news."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for incoming text messages."""
    if not agent:
        await update.message.reply_text("The agent is still initializing. Please wait a moment.")
        return

    prompt = update.message.text
    thread_id = str(update.message.chat_id)

    # Indicate typing while processing
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')

    try:
        # Semantic Cache Intercept
        embedding = create_embedding(prompt)
        cached_reply = get_cached_response(embedding)

        if cached_reply:
            print(f"[CACHE HIT] Answer served from Semantic Cache for query: '{prompt}'")
            await update.message.reply_text(f"⚡ {cached_reply}")
            return

        print(f"\n[CACHE MISS] Querying LLM and Tools for: '{prompt}'")
        config = {
            "configurable": {"thread_id": thread_id}
        }
        
        # We are inside an async function, so we can await directly instead of using asyncio.run
        response = await agent.ainvoke({"messages": [("user", prompt)]}, config)
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
        # Using asyncio.to_thread because save_to_cache uses synchronous psycopg connections
        await asyncio.to_thread(
            save_to_cache, 
            query=prompt, 
            response=reply, 
            embedding=embedding, 
            expires_in_hours=expires_in_hours
        )

        await update.message.reply_text(reply)

    except Exception as e:
        error_msg = f"Sorry, something went wrong: {e}"
        print(f"Error processing message: {e}")
        await update.message.reply_text(error_msg)

async def init_agent():
    """Initializes the agent asynchronously."""
    global agent
    print("Initializing MCP tools and agent...")
    tools = await load_mcp_tools()
    agent = build_agent(tools)
    print("Agent initialized successfully!")

if __name__ == "__main__":
    bot_token = "AAGf1M_n5MbD8q8ymSwaNLbTE ΒJTn4M6νQo"
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable is not set in .env")
        print("Please add TELEGRAM_BOT_TOKEN=your_bot_token_here to your .env file.")
        exit(1)

    print("Starting Telegram Bot...")
    
    # Initialize the application
    application = ApplicationBuilder().token(bot_token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # We need to initialize the agent before starting the bot.
    # python-telegram-bot handles the event loop. We can hook into post_init.
    
    async def post_init(app):
        await init_agent()
        
    application.post_init = post_init

    # Run the bot
    print("Bot is polling for messages. Press Ctrl+C to stop.")
    application.run_polling()
