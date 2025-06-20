import os
import json
import re
import random
from random import shuffle

from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# ── LOAD QUESTIONS ───────────────────────────────────────────
QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.json")
with open(QUESTIONS_PATH, "r") as f:
    QUESTIONS = json.load(f)

# ── CONFIG ───────────────────────────────────────────────────
WIN_AT             = int(os.getenv("WIN_AT", 10))
LOSE_AT            = int(os.getenv("LOSE_AT", 5))
BAR_LEN            = int(os.getenv("BAR_LEN", 10))
SLACK_BOT_TOKEN    = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

# ── APP INITIALIZATION ───────────────────────────────────────
app       = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app = Flask(__name__)
handler   = SlackRequestHandler(app)

# ── START GAME UI ────────────────────────────────────────────
start_ui = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*🎮 Welcome to CyberQuest!*\n\n"
                f"First to *{WIN_AT} correct* wins. First to *{LOSE_AT} wrong* loses.\n\n"
                "Click below to begin your challenge."
            )
        }
    },
    {"type": "divider"},
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔥 Start Game", "emoji": True},
                "action_id": "start_game_click",
                "value": "start"
            }
        ],
    },
]

# ── HELPERS ──────────────────────────────────────────────────
def progress_bar(correct: int, wrong: int) -> str:
    filled = "█" * min(correct, BAR_LEN)
    empty  = "░" * (BAR_LEN - len(filled))
    return f"[{filled}{empty}]  ✅ {correct}/{WIN_AT}  ❌ {wrong}/{LOSE_AT}"

def build_question_blocks(q_idx: int, correct: int, wrong: int):
    # Pick the question, shuffle its options
    q      = QUESTIONS[q_idx % len(QUESTIONS)]
    shuffle(q["options"])
    header = progress_bar(correct, wrong)

    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"{opt['id'].upper()}) {opt['txt']}"},
            "action_id": f"answer_{opt['id']}",
            "value": json.dumps({"q": q_idx, "answer": opt["id"], "c": correct, "w": wrong})
        }
        for opt in q["options"]
    ]

    return [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"{header}\n*Q{q_idx+1}:* {q['q']}"}
        },
        {"type": "actions", "elements": buttons}
    ]

# ── SLASH COMMAND ────────────────────────────────────────────
@app.command("/cyberquest")
def handle_start(ack, respond, command):
    ack()
    respond(blocks=start_ui, text="Ready for CyberQuest!")

# ── START BUTTON ────────────────────────────────────────────
@app.action("start_game_click")
def handle_start_click(ack, body, respond):
    ack()
    # Choose a random question index
    q_idx = random.randrange(len(QUESTIONS))
    # Build & send first question
    blocks = build_question_blocks(q_idx, 0, 0)
    respond(replace_original=True, blocks=blocks, text=QUESTIONS[q_idx]["q"])

# ── ANSWER BUTTONS ───────────────────────────────────────────
@app.action(re.compile(r"^answer_[a-z]$"))
def handle_answer(ack, body, respond):
    ack()
    data      = json.loads(body["actions"][0]["value"])
    q_idx     = int(data["q"])
    answer_id = data["answer"]
    correct   = int(data["c"])
    wrong     = int(data["w"])

    # Evaluate
    q   = QUESTIONS[q_idx % len(QUESTIONS)]
    opt = next(o for o in q["options"] if o["id"] == answer_id)
    correct += int(opt["ok"])
    wrong   += int(not opt["ok"])

    # Win/Lose
    if correct >= WIN_AT:
        return respond(replace_original=True, text=f"🏆 You win with {correct} correct!")
    if wrong >= LOSE_AT:
        return respond(replace_original=True, text=f"💀 Game over with {wrong} wrong.")

    # Feedback + Next
    feedback = (
        f"*{'✅ Correct!' if opt['ok'] else '❌ Incorrect.'}*\n{opt['why']}"
    )
    feedback_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": feedback}},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Next ▶️"},
                "action_id": "next_click",
                "value": json.dumps({"next": q_idx+1, "c": correct, "w": wrong})
            }
        ]}
    ]
    respond(replace_original=True, blocks=feedback_blocks)

# ── NEXT BUTTON ──────────────────────────────────────────────
@app.action("next_click")
def handle_next(ack, body, respond):
    ack()
    data    = json.loads(body["actions"][0]["value"])
    q_idx   = int(data["next"])
    correct = int(data["c"])
    wrong   = int(data["w"])
    blocks  = build_question_blocks(q_idx, correct, wrong)
    respond(replace_original=True, blocks=blocks,
            text=QUESTIONS[q_idx % len(QUESTIONS)]["q"])

# ── FLASK ROUTES ────────────────────────────────────────────
@flask_app.route("/slack/commands", methods=["POST"])
def slack_commands():
    return handler.handle(request)

@flask_app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    return handler.handle(request)

@flask_app.route("/", methods=["GET"])
def health():
    return "OK", 200

# ── RUN LOCALLY ─────────────────────────────────────────────
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
