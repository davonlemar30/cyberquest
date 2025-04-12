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

Respond with short, Slack-formatted messages that simulate common security situations. The user works at a company called Microcom. They might receive suspicious emails, links, files, or messages that test their ability to spot red flags.

Use simple language. Never assume technical knowledge. Always explain the risk through story and subtle clues.

At the end of each message, include 2 to 4 action choices beginning with a bullet (•). NEVER write a wall of text.

Do not use job titles. Just make it feel like the user is someone working at Microcom handling their daily routine."""
        ]
    }
]

        )
        chat_sessions[conversation_id] = session
    return chat_sessions[conversation_id]

# 🧠 Gemini interaction
def call_gemini_flash(user_input, conversation_id):
    try:
        session = get_chat_session(conversation_id)
        response = session.send_message(user_input)
        return response.text
    except Exception as e:
        return f"⚠️ Gemini Error: {e}"

# 🔤 Format Gemini text for Slack
def format_for_slack(text):
    text = text.replace("**", "*").replace("##", "*").replace(" - ", "• ").replace("  ", " ")
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

# 🟡 Extract choices from Gemini response
def extract_choices(text):
    lines = text.split("\n")
    choices = []
    for line in lines:
        if line.strip().startswith("•"):
            label = line.strip("• ").strip()
            if label:
                choices.append(label)
    return choices

# 🔳 Build Slack button blocks
def build_slack_blocks(formatted_reply, choices):
    buttons = []
    for i, choice in enumerate(choices[:5]):
        buttons.append({
            "type": "button",
            "text": { "type": "plain_text", "text": choice },
            "action_id": f"choice_{i}",
            "value": choice
        })
    return [
        {
            "type": "section",
            "text": { "type": "mrkdwn", "text": formatted_reply }
        },
        {
            "type": "actions",
            "elements": buttons
        }
    ]

# 🚪 Slash command entrypoint
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

# 🧵 Handles Slack slash command async
def handle_gemini_response(response_url, user_input, user_id):
    raw_reply = call_gemini_flash(user_input, user_id)
    formatted_reply = format_for_slack(raw_reply)
    choices = extract_choices(raw_reply)
    blocks = build_slack_blocks(formatted_reply, choices)

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": blocks
    })

# 📥 Slack Interactivity Endpoint
@app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    payload = request.form.get("payload")
    data = json.loads(payload)

    choice = data["actions"][0]["value"]
    user_id = data["user"]["id"]
    response_url = data["response_url"]

    reply = call_gemini_flash(choice, user_id)
    formatted_reply = format_for_slack(reply)
    choices = extract_choices(reply)
    blocks = build_slack_blocks(formatted_reply, choices)

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": blocks
    })

    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
