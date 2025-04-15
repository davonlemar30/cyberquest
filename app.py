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
                        """
Welcome to *CyberQuest: Security Training*! Your goal is to make safe choices as you navigate everyday work life at Microcom. Your progress will be tracked.

Start with the main menu and select an option to begin.
"""
                    ]
                }
            ]
        )
        chat_sessions[conversation_id] = {
            "session": session,
            "score": 0
        }
    return chat_sessions[conversation_id]["session"]

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
    text = text.replace("**", "*").replace("##", "*").replace("  ", " ")
    text = text.replace(" - ", "• ")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    text = "\n\n".join(paragraphs)

    lines = text.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("•"):
            continue
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

def extract_bullet_choices(text, limit=40):
    lines = text.split("\n")
    choices = []
    for line in lines:
        if line.strip().startswith("•"):
            label = line.strip("• ").strip()
            if label:
                if len(label) > limit:
                    label = label.split()[0:6]
                    label = " ".join(label).strip(" .")
                choices.append(label)
    return choices

def truncate_label(label, limit=35):
    return (label[:limit - 1] + "…") if len(label) > limit else label

##########################################
# 4. Build Slack Blocks
##########################################
def build_slack_blocks(raw_reply, score=None):
    scenario_text = format_scenario_text(raw_reply)
    choice_list = extract_bullet_choices(raw_reply)

    scenario_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": scenario_text if scenario_text else "_(No scenario text)_"
        }
    }

    score_block = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"*Score:* {score}" if score is not None else "_"
            }
        ]
    }

    buttons = []
    for i, full_choice in enumerate(choice_list[:5]):
        buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": truncate_label(full_choice)
            },
            "value": full_choice,
            "action_id": f"choice_{i}"
        })

    actions_block = {
        "type": "actions",
        "elements": buttons
    }

    return [scenario_block, score_block, actions_block]

##########################################
# 5. Slack Endpoints
##########################################
@app.route("/cyberquest", methods=["POST"])
def cyberquest():
    user_input = request.form.get("text")
    user_id = request.form.get("user_id")
    response_url = request.form.get("response_url")

    if user_input.strip().lower() in ["menu", "start"]:
        main_menu = {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Start Training"}, "value": "start", "action_id": "start_training"},
                {"type": "button", "text": {"type": "plain_text", "text": "How to Play"}, "value": "help", "action_id": "how_to_play"},
                {"type": "button", "text": {"type": "plain_text", "text": "Exit"}, "value": "exit", "action_id": "exit_game"}
            ]
        }

        return jsonify({
            "response_type": "in_channel",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "*Welcome to CyberQuest Training!* Choose an option below:"}},
                main_menu
            ]
        })

    threading.Thread(target=handle_gemini_response, args=(response_url, user_input, user_id)).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "🧠 Processing your CyberQuest move..."
    })

def handle_gemini_response(response_url, user_input, user_id):
    raw_reply = call_gemini_flash(user_input, user_id)
    score = chat_sessions.get(user_id, {}).get("score", 0)
    blocks = build_slack_blocks(raw_reply, score)

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

    if choice == "start":
        chat_sessions[user_id] = {"session": get_chat_session(user_id), "score": 0}
        raw_reply = call_gemini_flash("start training", user_id)
    elif choice == "help":
        raw_reply = "CyberQuest is a text-based security training game. You’ll receive fake emails, messages, or alerts and choose what action to take. Click Start Training to begin."
    elif choice == "exit":
        raw_reply = "You've exited CyberQuest. Type `/cyberquest start` to begin again."
    else:
        raw_reply = call_gemini_flash(choice, user_id)
        if "report" in choice.lower():
            chat_sessions[user_id]["score"] += 1
        elif "click" in choice.lower() or "open" in choice.lower():
            chat_sessions[user_id]["score"] -= 1

    score = chat_sessions.get(user_id, {}).get("score", 0)
    blocks = build_slack_blocks(raw_reply, score)

    requests.post(response_url, json={
        "response_type": "in_channel",
        "blocks": blocks
    })

    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
