from google import genai
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
import os
import threading
import re
from flask import Flask, request
from email_sender import send_ticket_email
import json                    
from random import shuffle


# Load environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Define Slacky's personality as system instructions
personality_instruction = (
    "You are Slacky 2.0, a calm and efficient IT assistant for Microcom. "
    "You respond clearly and concisely, using a friendly but professional tone. "
    "Avoid unnecessary flair or personality; focus on solving problems, giving helpful answers, and saving users time. "
    "Only offer humor or warmth when it supports clarity or reduces stress in a tense situation. "
    "Tech should feel simple and approachable—skip jargon unless it's necessary, and explain only as much as the user needs."
)


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

# ── 1) Question bank ──────────────────────────────────────────────────────
QUESTIONS = [
    {
        "q": "Which is the biggest red-flag in a phishing email?",
        "options": [
            {"id": "a", "txt": "Unexpected attachment from HR", "ok": True},
            {"id": "b", "txt": "CC’d to your manager",           "ok": False},
            {"id": "c", "txt": "Perfect spelling",               "ok": False},
            {"id": "d", "txt": "Fancy signature block",          "ok": False},
        ]
    },
    {
        "q": "A co-worker DMs you a weird link. What’s your FIRST move?",
        "options": [
            {"id": "a", "txt": "Click it and see",               "ok": False},
            {"id": "b", "txt": "Ask if they really sent it",     "ok": True},
            {"id": "c", "txt": "Forward to everyone",            "ok": False},
            {"id": "d", "txt": "Ignore and hope for the best",   "ok": False},
        ]
    },
    # …add as many as you like
]

# ── 2) Constants ──────────────────────────────────────────────────────────
WIN_AT   = 10          # hit 10 correct → win
LOSE_AT  = 5           # hit 5 wrong   → lose
BAR_LEN  = 10          # length of the progress bar

# ── 3) Gemini helper (unchanged) ──────────────────────────────────────────
def explain_with_gemini(question, choice_text, is_correct):
    prompt = (
        "You are CyberQuest, an upbeat IT-security mentor.\n"
        f"Question: {question}\n"
        f"Employee chose: {choice_text}\n"
        f"Was that correct? {'Yes' if is_correct else 'No'}.\n"
        "Explain why in ≤35 words."
    )
    reply = client.chat.completions.create(
        model="gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=80,
        temperature=0.4,
    )
    return reply.choices[0].message.content.strip()

# ── 4) Pretty progress bar ────────────────────────────────────────────────
def progress_bar(correct, wrong):
    filled  = min(correct, BAR_LEN)
    empty   = BAR_LEN - filled
    bar     = "█"*filled + "░"*empty
    return f"`[{bar}]`  ✅ {correct}/{WIN_AT}   ❌ {wrong}/{LOSE_AT}"

# ── 5) Send one question ──────────────────────────────────────────────────
def post_question(channel_id, q_idx, correct, wrong):
    q = QUESTIONS[q_idx % len(QUESTIONS)]     # wrap if we run out
    shuffle(q["options"])
    head = progress_bar(correct, wrong)

    blocks = [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"{head}\n*Q{q_idx+1}*  {q['q']}"}},
        {"type": "actions",
         "elements": [
             {
                 "type": "button",
                 "text": {"type": "plain_text",
                          "text": f"{opt['id'].upper()}) {opt['txt']}"},
                 "action_id": "answer_click",
                 "value": json.dumps({"q": q_idx, "o": i,
                                      "c": correct, "w": wrong})
             } for i, opt in enumerate(q["options"])
         ]}
    ]
    app.client.chat_postMessage(channel=channel_id, blocks=blocks, text=q["q"])

# ── 6) /cyberquest slash-command ──────────────────────────────────────────
@app.command("/cyberquest")
def start_cyberquest(ack, body):
    ack()
    post_question(body["channel_id"], 0, 0, 0)    # start at 0-0

# ── 7) Handle A/B/C/D button click ────────────────────────────────────────
@app.action("answer_click")
def handle_answer_click(ack, body, respond):
    ack()
# ----- inside handle_answer_click -----------------------
data = json.loads(body["actions"][0]["value"])

# make SURE they're ints every time  📌
q_idx   = int(data["q"])
o_idx   = int(data["o"])
correct = int(data["c"])
wrong   = int(data["w"])
# --------------------------------------------------------


    q   = QUESTIONS[q_idx % len(QUESTIONS)]
    opt = q["options"][o_idx]

    # update tallies
    if opt["ok"]:
        correct += 1
    else:
        wrong += 1

    # instant win / lose check
    if correct >= WIN_AT:
        respond(replace_original=True,
                text=f"🏆 *Perfect! You reached {WIN_AT} correct answers!*")
        return
    if wrong >= LOSE_AT:
        respond(replace_original=True,
                text=f"💀 *Game over!* You hit {LOSE_AT} incorrect answers.")
        return

    # explanation + Next ▶️
    reason = explain_with_gemini(q["q"], opt["txt"], opt["ok"])
    blocks = [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"*{'✅ Correct!' if opt['ok'] else '❌ Incorrect.'}*\n{reason}"}},
        {"type": "actions",
         "elements": [
             {
                 "type": "button",
                 "text": {"type": "plain_text", "text": "Next ▶️"},
                 "action_id": "next_click",
                 "value": json.dumps({"next": q_idx + 1,
                                      "c": correct, "w": wrong})
             }
         ]}
    ]
    respond(replace_original=True, blocks=blocks)

# ── 8) Handle Next ▶️ ─────────────────────────────────────────────────────
@app.action("next_click")
def handle_next_click(ack, body, respond):
    ack()
    data    = json.loads(body["actions"][0]["value"])
    q_idx   = data["next"]
    correct = data["c"]
    wrong   = data["w"]
    channel = body["channel"]["id"]

    respond(delete_original=True)   # clean up feedback balloon
    post_question(channel, q_idx, correct, wrong)

# ========== CYBERQUEST QUIZ v3 END ==========

def process_ticket(body):
    print("🔧 process_ticket started")
    ...
    try:
        send_ticket_email(user_email, user_name, issue_text)
        print(f"✅ Ticket email sent for {user_email}")
    except Exception as ex:
        print(f"❌ Email send failed for {user_email}: {ex}", flush=True)
        raise   # re-raise so Cloud Run logs the traceback


def remove_markdown(text):
    """Removes common markdown characters to keep Slack messages clean."""
    return re.sub(r"[*_`~]", "", text)

# Dictionary to hold chat sessions keyed by conversation (channel) ID
chat_sessions = {}

def get_chat_session(conversation_id):
    """
    Retrieve or create a chat session for the conversation.
    Each new session is seeded with Slacky's personality instructions.
    """
    if conversation_id not in chat_sessions:
        session = client.chats.create(model="gemini-2.0-flash")
        # Seed the chat session with the personality prompt
        session.send_message(personality_instruction)
        chat_sessions[conversation_id] = session
    return chat_sessions[conversation_id]

def generate_chat_response(conversation_id, user_message):
    """
    Send a message to the persistent chat session.
    The session includes previous turns to maintain context.
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
