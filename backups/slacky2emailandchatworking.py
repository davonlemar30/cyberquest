from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
import os
import threading
from flask import Flask, request
from email_sender import send_ticket_email
from google import genai  # Correct import per Gemini quickstart

# Load environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Initialize the Gemini client using the google-genai package
client = genai.Client(api_key=GEMINI_API_KEY)

# Initialize the Slack Bolt App
app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET
)

##############################
# EVENT HANDLERS FOR CONVERSATION
##############################

# Handler for app mentions in channels
@app.event("app_mention")
def handle_app_mention(body, say):
    user_message = body["event"]["text"]
    try:
        # Generate a text response using Gemini's generate_content method
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_message  # pass as a string
        )
        message = response.text if hasattr(response, "text") else "No response from Gemini."
    except Exception as e:
        message = f"Error generating response: {e}"
    say(message)

# Handler for direct messages (IMs)
@app.event("message")
def handle_direct_message(body, say):
    event = body["event"]
    if event.get("channel_type") == "im":
        user_message = event["text"]
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=user_message  # pass as a string
            )
            message = response.text if hasattr(response, "text") else "No response from Gemini."
        except Exception as e:
            message = f"Error generating response: {e}"
        say(message)

##############################
# SLASH COMMAND: /ticket (Email Ticketing System)
##############################

@app.command("/ticket")
def handle_ticket_command(ack, body):
    # Immediately acknowledge the command to avoid Slack timeouts
    ack("📨 Ticket submitted successfully! We'll follow up via email.")
    # Offload ticket processing to a background thread
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
