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

##########################################
# 1. Load Credentials & Configure Gemini
##########################################
def get_google_credentials():
    encoded = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not encoded:
        raise Exception("Missing GEMINI_SERVICE_ACCOUNT in environment")
    service_account_info = json.loads(base64.b64decode(encoded).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/generative-language"]
    )

credentials = get_google_credentials()
genai.configure(credentials=credentials)

##########################################
# 2. Chat Session Management
##########################################
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

def call_gemini_flash(user_input, conversation_id):
    try:
        session = get_chat_session(conversation_id)
        response = session.send_message(user_input)
        print("Gemini response raw:", response.text)
        return response.text
    except Exception as e:
        return f"⚠️ Gemini Error: {e}"

##########################################
# 3. Formatting & Extraction
##########################################
def format_scenario_text(text):
    """
    Formats the main scenario text for Slack, removing bullet lines entirely
    so we don't repeat them in the scenario. Bullets will appear as buttons only.
    """
    # Basic cleanup
    text = text.replace("**", "*").replace("##", "*").replace("  ", " ")
    text = text.replace(" - ", "• ")  # optional conversion of dash to bullet

    # Split paragraphs on double newlines
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    text = "\n\n".join(paragraphs)

    lines = text.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()

        # If line starts with bullet, skip it
        if stripped.startswith("•"):
            continue

        # Additional highlights or formatting
        if "From:" in stripped or "Subject:" in stripped:
            line = f":email: *{stripped}*"
        elif "report" in stripped.lower():
            line = f":warning: {stripped}"
        elif "IP" in stripped or "192." in stripped:
            line = f":mag_right: `{stripped}`"
        elif (stripped.lower().startswith("what do you") or 
              stripped.lower().startswith("what’s next") or 
              stripped.lower().startswith("what is your next move")):
            line = f"\n*{stripped}*"

        filtered_lines.append(line)

    return "\n".join(filtered_lines).strip()

def extract_bullet_choices(text):
    """
    Pull bullet lines from the raw text. Example of bullet line:
    • Click the link
    """
    lines = text.split("\n")
    choices = []
    for line in lines:
        if line.strip().startswith("•"):
            # remove "• " from the beginning
            label = line.strip("• ").strip()
            if label:
                choices.append(label)
    return choices

def truncate_label(label, limit=35):
    """
    Shortens a label for Slack button if it's too long,
    but pass the full text via 'value' to Gemini.
    """
    return (label[:limit - 1] + "…") if len(label) > limit else label

##########################################
# 4. Build Slack Blocks
##########################################
def build_slack_blocks(raw_reply):
    # Format scenario text (removing bullet lines)
    scenario_text = format_scenario_text(raw_reply)
    # Extract bullet lines for building clickable buttons
    choice_list = extract_bullet_choices(raw_reply)

    # Main scenario block
    scenario_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": scenario_text if scenario_text else "_(No scenario text)_"
        }
    }

    # Buttons block
    buttons = []
    for i, full_choice in enumerate(choice_list[:5]):
        buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": truncate_label(full_choice)
            },
            "value": full_choice,  # pass entire label to the backend
            "action_id": f"choice_{i}"
        })

    actions_block = {
        "type": "actions",
        "elements": buttons
    }

    return [scenario_block, actions_block]

##########################################
# 5. Slack Endpoints
##########################################
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

def handle_gemini_response(response_url, user_input, user_id):
    raw_reply = call_gemini_flash(user_input, user_id)
    blocks = build_slack_blocks(raw_reply)

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": blocks
    })

@app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    payload = request.form.get("payload")
    data = json.loads(payload)

    choice = data["actions"][0]["value"]
    user_id = data["user"]["id"]
    response_url = data["response_url"]

    # pass user choice to Gemini
    raw_reply = call_gemini_flash(choice, user_id)
    blocks = build_slack_blocks(raw_reply)

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": blocks
    })

    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
