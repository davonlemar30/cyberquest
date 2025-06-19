from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
import os
import threading
from flask import Flask, request
from email_sender import send_ticket_email
import google.generativeai as genai

# Load environment variables (ensure these are set in your environment or via Cloud Run)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Configure the Gemini API with your API key
genai.configure(api_key=GEMINI_API_KEY)

# Initialize the Slack Bolt App
app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET
)

##############################
# EVENT HANDLERS
##############################

# Respond when the bot is mentioned in a channel using Gemini for a reply
@app.event("app_mention")
def mention_handler(body, say):
    user_message = body["event"]["text"]
    response = genai.generate_text(prompt=user_message, model="gemini-2.0-flash")
    say(response.text)

# Respond to direct messages with a Gemini-generated reply
@app.event("message")
def handle_dm_events(body, say):
    event = body["event"]
    if event.get("channel_type") == "im":
        user_message = event["text"]
        response = genai.generate_text(prompt=user_message, model="gemini-2.0-flash")
        say(response.text)

# Slash Command: /ticket
@app.command("/ticket")
def handle_ticket_command(ack, body):
    # Immediately acknowledge the command to avoid timeout
    ack("📨 Ticket submitted successfully! We'll follow up via email.")
    
    # Process the ticket in a background thread so that the ack is returned immediately.
    threading.Thread(target=process_ticket, args=(body,)).start()

def process_ticket(body):
    # Extract the user ID and command text from the payload
    user_id = body.get("user_id")
    issue_text = body.get("text", "").strip()

    try:
        # Retrieve user info from Slack
        user_info = app.client.users_info(user=user_id)
        user_profile = user_info["user"]["profile"]
        user_email = user_profile.get("email")
        user_name = user_profile.get("real_name", "User")
    except Exception as e:
        # Log error (cannot update Slack anymore since we've already acked)
        print(f"❌ Error retrieving user info: {e}")
        return

    try:
        # Send the ticket email (asynchronously)
        send_ticket_email(user_email, user_name, issue_text)
        print(f"✅ Ticket email sent successfully for {user_email}")
    except Exception as ex:
        print(f"❌ Failed to send ticket email for {user_email}: {ex}")

##############################
# FLASK APP SETUP
##############################

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

##############################
# RUN THE APP ON PORT 8080
##############################

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
