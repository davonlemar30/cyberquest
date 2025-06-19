from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
import os
import threading
import re
from flask import Flask, request
from email_sender import send_ticket_email
from google import genai  # Using google-genai per Gemini quickstart

# Load environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Initialize the Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# Initialize the Slack Bolt App
app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET
)

##############################
# HELPER FUNCTIONS
##############################

def remove_markdown(text):
    """Removes common markdown characters to keep Slack messages clean."""
    return re.sub(r"[*_`~]", "", text)

# Dictionary to hold chat sessions keyed by conversation (channel) ID
chat_sessions = {}

def get_chat_session(conversation_id):
    """Retrieve or create a chat session for the conversation."""
    if conversation_id not in chat_sessions:
        # Create a new chat session that will automatically accumulate context.
        chat_sessions[conversation_id] = client.chats.create(model="gemini-2.0-flash")
    return chat_sessions[conversation_id]

def generate_chat_response(conversation_id, user_message):
    """
    Send a message to the persistent chat session.
    The session will include previous turns in the context.
    """
    session = get_chat_session(conversation_id)
    response = session.send_message(user_message)
    return remove_markdown(response.text) if hasattr(response, "text") else "No response from Gemini."

##############################
# EVENT HANDLERS WITH CONTEXT MEMORY
##############################

# Handler for app mentions in channels
@app.event("app_mention")
def handle_app_mention(body, say):
    event = body.get("event", {})
    # Filter out duplicate or bot events if needed
    if event.get("subtype") or event.get("bot_id"):
        return
    user_message = event.get("text", "")
    channel = event.get("channel")
    
    # Simulate typing by sending a placeholder
    placeholder_response = say(text="...thinking...", channel=channel)
    
    try:
        # Generate a response using the persistent chat session.
        final_response = generate_chat_response(channel, user_message)
    except Exception as e:
        final_response = f"Error generating response: {e}"
    
    # Update the placeholder message with the actual response.
    app.client.chat_update(
        channel=channel,
        ts=placeholder_response["ts"],
        text=final_response
    )

# Handler for direct messages (IMs)
@app.event("message")
def handle_direct_message(body, say):
    event = body.get("event", {})
    # Only process direct messages that aren’t from bots
    if event.get("channel_type") == "im" and not event.get("bot_id") and not event.get("subtype"):
        user_message = event.get("text", "")
        channel = event.get("channel")
        
        placeholder_response = say(text="...thinking...", channel=channel)
        
        try:
            final_response = generate_chat_response(channel, user_message)
        except Exception as e:
            final_response = f"Error generating response: {e}"
        
        app.client.chat_update(
            channel=channel,
            ts=placeholder_response["ts"],
            text=final_response
        )

##############################
# SLASH COMMAND: /ticket (Email Ticketing System)
##############################

@app.command("/ticket")
def handle_ticket_command(ack, body):
    ack("📨 Ticket submitted successfully! We'll follow up via email.")
    threading.Thread(target=process_ticket, args=(body,)).start()

def process_ticket(body):
    user_id = body.get("user_id")
    issue_text = body.get("text", "").strip()
    try:
        user_info = app.client.users_info(user=user_id)
        user_profile = user_info["user"]["profile"]
        user_email = user_profile.get("email")
        user_name = user_profile.get("real_name", "User")
    except Exception as e:
        print(f"❌ Error retrieving user info: {e}")
        return

    try:
        send_ticket_email(user_email, user_name, issue_text)
        print(f"✅ Ticket email sent successfully for {user_email}")
    except Exception as ex:
        print(f"❌ Failed to send ticket email for {user_email}: {ex}")

##############################
# FLASK APP SETUP FOR SLACK EVENTS
##############################

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

##############################
# RUN THE APP
##############################

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
