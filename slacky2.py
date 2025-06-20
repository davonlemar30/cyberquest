import os
import json
import re
import random
from random import shuffle

from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# In-memory store of active quizzes: user_id → {q_idx, correct, wrong}
sessions: dict[str, dict[str, int]] = {}


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
    user = body["user"]["id"]
    # initialize a new session for this user
    sessions[user] = {
        "q_idx": random.randrange(len(QUESTIONS)),
        "correct": 0,
        "wrong": 0
    }
    state = sessions[user]
    blocks = build_question_blocks(
        state["q_idx"],
        state["correct"],
        state["wrong"]
    )
    respond(
        replace_original=True,
        blocks=blocks,
        text=QUESTIONS[state["q_idx"]]["q"]
    )

# ── ANSWER BUTTONS ───────────────────────────────────────────
@app.action(re.compile(r"^answer_[a-z]$"))
def handle_answer(ack, body, respond):
    ack()
    user = body["user"]["id"]
    # load session
    state = sessions.get(user)
    if not state:
        # no session? ask them to start again
        return respond(text="❗ No active game. Type `/start` to begin.")

    # unpack
    q_idx   = state["q_idx"]
    correct = state["correct"]
    wrong   = state["wrong"]

    # get their choice
    data      = json.loads(body["actions"][0]["value"])
    answer_id = data["answer"]

    # evaluate
    q   = QUESTIONS[q_idx % len(QUESTIONS)]
    opt = next(o for o in q["options"] if o["id"] == answer_id)
    if opt["ok"]:
        correct += 1
    else:
        wrong   += 1

    # store back
    state["correct"] = correct
    state["wrong"]   = wrong

    # Win / Lose?
    if correct >= WIN_AT:
        # clear session
        del sessions[user]
        return respond(
            replace_original=True,
            text=f"🏆 *You win!* {correct}/{WIN_AT} correct. Type `/start` to play again."
        )
    if wrong >= LOSE_AT:
        del sessions[user]
        return respond(
            replace_original=True,
            text=f"💀 *Game over!* {wrong}/{LOSE_AT} wrong. Type `/start` to try again."
        )

    # otherwise, show feedback + Next
    feedback_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{'✅ Correct!' if opt['ok'] else '❌ Incorrect.'}*\n{opt['why']}"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Next ▶️"},
                    "action_id": "next_click"
                }
            ]
        }
    ]
    respond(replace_original=True, blocks=feedback_blocks)


# ── NEXT BUTTON ──────────────────────────────────────────────
@app.action("next_click")
def handle_next(ack, body, respond):
    ack()
    user = body["user"]["id"]
    state = sessions.get(user)
    if not state:
        return respond(text="❗ No active game. Type `/start` to begin.")
    # increment question index
    state["q_idx"] += 1
    q_idx, correct, wrong = state["q_idx"], state["correct"], state["wrong"]
    blocks = build_question_blocks(q_idx, correct, wrong)
    respond(
        replace_original=True,
        blocks=blocks,
        text=QUESTIONS[q_idx % len(QUESTIONS)]["q"]
    )


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
