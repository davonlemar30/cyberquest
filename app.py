from flask import Flask, request, jsonify
import os
import requests
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
    """
    Returns an existing session or creates a new one if user_id not in chat_sessions.
    Each session is tied to the user and also tracks a 'score'.
    """
    if conversation_id not in chat_sessions:
        # Start a fresh conversation with a short intro
        session = genai.GenerativeModel("models/gemini-1.5-flash").start_chat(
            history=[
                {
                    "role": "user",
                    "parts": [
                        """Welcome to *CyberQuest: Security Training!* 
Keep all responses short and realistic. Provide 2-4 bullet actions at the end of each scenario. 
All messaging is ephemeral, so only the user sees it."""
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
    """
    Passes user_input to Gemini for that user's session.
    Logs raw text for debugging.
    """
    try:
        session = get_chat_session(conversation_id)
        response = session.send_message(user_input)
        print("Gemini response raw:", response.text)  # for debugging
        return response.text
    except Exception as e:
        return f"⚠️ Gemini Error: {e}"

##########################################
# 3. Formatting & Extraction
##########################################
def format_scenario_text(text):
    """
    Removes bullet lines (we turn them into Slack buttons).
    Slack-ifies 'From:' and 'Subject:' lines, etc.
    """
    text = text.replace("**", "*").replace("##", "*").replace("  ", " ")
    text = text.replace(" - ", "• ")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    text = "\n\n".join(paragraphs)

    lines = text.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        # skip bullet lines
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
    """
    Finds lines like '• Click the link' => 'Click the link'
    Also shortens them if they exceed length limit.
    """
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
    """
    Slack button text can visually truncate. We do it ourselves for clarity.
    """
    return (label[:limit - 1] + "…") if len(label) > limit else label

##########################################
# 4. Build Slack Blocks
##########################################
def build_slack_blocks(raw_reply, score=0):
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
                "text": f"*Score:* {score}"
            }
        ]
    }

    # Buttons from bullet lines
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
# 5. Slack Endpoints (All ephemeral)
##########################################

@app.route("/cyberquest", methods=["POST"])
def cyberquest():
    """
    Slack slash command: /cyberquest
    If user types 'menu' or 'start', show ephemeral main menu.
    Otherwise, we run the scenario immediately (no background thread).
    """
    user_input = request.form.get("text", "").strip().lower()
    user_id = request.form.get("user_id")

    # Show ephemeral main menu if 'menu' or 'start'
    if user_input in ["menu", "start"]:
        main_menu = {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Start Training"},
                    "value": "start",
                    "action_id": "start_training"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "How to Play"},
                    "value": "help",
                    "action_id": "how_to_play"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Exit"},
                    "value": "exit",
                    "action_id": "exit_game"
                }
            ]
        }

        return jsonify({
            "response_type": "ephemeral",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Welcome to CyberQuest Training!* Choose an option below (ephemeral)."
                    }
                },
                main_menu
            ]
        })
    else:
        # For other text, let's run Gemini scenario inline (no background thread).
        raw_reply = call_gemini_flash(user_input, user_id)
        score = chat_sessions.get(user_id, {}).get("score", 0)
        blocks = build_slack_blocks(raw_reply, score)

        return jsonify({
            "response_type": "ephemeral",
            "blocks": blocks
        })

@app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    """
    Slack interactive endpoint for button clicks.
    We parse the clicked value, update scenario or do special actions, then return ephemeral.
    """
    payload = request.form.get("payload")
    data = json.loads(payload)

    choice = data["actions"][0]["value"]
    user_id = data["user"]["id"]

    # The user might not have a session yet, so ensure it
    get_chat_session(user_id)  # creates or returns existing

    # Score logic or special commands
    if choice == "start":
        chat_sessions[user_id]["score"] = 0
        raw_reply = call_gemini_flash("start training", user_id)
    elif choice == "help":
        raw_reply = (
            "CyberQuest is ephemeral. Each scenario is private to you. "
            "Pick an action to respond, and we'll track your 'score' for good/bad choices. "
            "Type `/cyberquest start` any time to restart."
        )
    elif choice == "exit":
        raw_reply = "You've exited CyberQuest. Type `/cyberquest start` or `/cyberquest menu` to re-enter."
    else:
        # pass the choice text to Gemini
        raw_reply = call_gemini_flash(choice, user_id)
        # update user score
        if "report" in choice.lower():
            chat_sessions[user_id]["score"] += 1
        elif "click" in choice.lower() or "open" in choice.lower():
            chat_sessions[user_id]["score"] -= 1

    score = chat_sessions[user_id]["score"]
    blocks = build_slack_blocks(raw_reply, score)

    # ephemeral response to user
    return jsonify({
        "response_type": "ephemeral",
        # No replace_original => each response is a separate ephemeral bubble
        "blocks": blocks
    })

if __name__ == "__main__":
    app.run(debug=True)
