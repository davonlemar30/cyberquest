from flask import Flask, request, jsonify
import os
import requests
import threading
import base64
import json
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}

# 🔐 Load credentials from base64 JSON (Render ENV)
def get_google_credentials():
    encoded = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not encoded:
        raise Exception("Missing GEMINI_SERVICE_ACCOUNT in environment")
    service_account_info = json.loads(base64.b64decode(encoded).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/generative-language"]
    )

# 🔁 Initialize Gemini client once
credentials = get_google_credentials()
genai.configure(credentials=credentials)

# 💬 Manage conversation sessions
def get_chat_session(conversation_id):
    if conversation_id not in chat_sessions:
        session = genai.GenerativeModel("models/gemini-1.5-flash").start_chat(
            history=[
                {
                    "role": "user",
                    "parts": [
                        """You are the narrator of a Slack-based cybersecurity text adventure game called *CyberQuest*.

Respond with clear, Slack-formatted responses using:
- *bold* for emphasis
- bullet points for options
- line breaks for clarity
- NEVER write in one long wall of text

Be immersive, but break things into readable chunks. Ask the player what they want to do next."""
                    ]
                }
            ]
        )
        chat_sessions[conversation_id] = session
    return chat_sessions[conversation_id]


# 🧠 Main Gemini interaction
def call_gemini_flash(user_input, conversation_id):
    try:
        session = get_chat_session(conversation_id)
        response = session.send_message(user_input)
        return response.text
    except Exception as e:
        return f"⚠️ Gemini Error: {e}"

# 🧵 Background thread handler for Slack
def handle_gemini_response(response_url, user_input, user_id):
    raw_reply = call_gemini_flash(user_input, user_id)
    formatted_reply = format_for_slack(raw_reply)

    # Send Slack Block Kit message with buttons
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_reply
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Check #general"
                    },
                    "action_id": "check_general"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Read DM"
                    },
                    "action_id": "read_dm"
                }
            ]
        }
    ]

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": blocks
    })


def format_for_slack(text):
    # Basic cleanup
    text = text.replace("**", "*")  # Markdown to Slack
    text = text.replace("##", "*")  # Markdown headings
    text = text.replace(" - ", "• ")  # Convert list dashes
    text = text.replace("  ", " ")

    # Keyword cleanup for structure
    lines = text.split("\n")
    formatted = []

    for line in lines:
        if "From:" in line or "Subject:" in line:
            line = f":email: *{line.strip()}*"
        elif "IP" in line or "192." in line:
            line = f":mag_right: `{line.strip()}`"
        elif "report" in line.lower():
            line = f":warning: {line.strip()}"
        elif line.strip().lower().startswith("what do you"):
            line = f"\n*{line.strip()}*"

        formatted.append(line)

    return "\n".join(formatted).strip()



# 🚪 Slack endpoint
@app.route("/cyberquest", methods=["POST"])
def cyberquest():
    user_input = request.form.get("text")
    user_id = request.form.get("user_id")
    response_url = request.form.get("response_url")

    threading.Thread(target=handle_gemini_response, args=(response_url, user_input, user_id)).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "🧠 Processing your CyberQuest move..."
    })

if __name__ == "__main__":
    app.run(debug=True)

@app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    payload = request.form.get("payload")
    data = json.loads(payload)

    action_id = data["actions"][0]["action_id"]
    user_id = data["user"]["id"]
    response_url = data["response_url"]

    if action_id == "check_general":
        reply = call_gemini_flash("check #general", user_id)

    elif action_id == "read_dm":
        reply = call_gemini_flash("read direct message", user_id)

    else:
        reply = "🤖 I didn’t understand that action."

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": reply
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": { "type": "plain_text", "text": "Check #general" },
                        "action_id": "check_general"
                    },
                    {
                        "type": "button",
                        "text": { "type": "plain_text", "text": "Read DM" },
                        "action_id": "read_dm"
                    }
                ]
            }
        ]
    })

    return "", 200

