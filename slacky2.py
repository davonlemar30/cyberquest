import os
import json
import re
import random
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

# In-memory store of active quizzes
# Each session now has: queue (shuffled indices), step, correct, wrong
sessions: dict[str, dict] = {}

# ── LOAD QUESTIONS ───────────────────────────────────────────
QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.json")
with open(QUESTIONS_PATH, "r") as f:
    QUESTIONS = json.load(f)

# ── CONFIG ───────────────────────────────────────────────────
WIN_AT               = int(os.getenv("WIN_AT", 10))
LOSE_AT              = int(os.getenv("LOSE_AT", 5))
BAR_LEN              = int(os.getenv("BAR_LEN", 10))
SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

# ── APP INIT ─────────────────────────────────────────────────
app       = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app = Flask(__name__)
handler   = SlackRequestHandler(app)

# ── START GAME UI ────────────────────────────────────────────
start_ui = [
    {"type": "section",
     "text": {"type": "mrkdwn",
              "text": (
                  "*🎮 Welcome to CyberQuest!*\n\n"
                  f"First to *{WIN_AT}* correct wins. First to *{LOSE_AT}* wrong loses.\n\n"
                  "Click below to begin."
              )
     }},
    {"type": "divider"},
    {"type": "actions", "elements": [
        {"type": "button",
         "text": {"type": "plain_text", "text": "🔥 Start Game", "emoji": True},
         "action_id": "start_game_click",
         "value": "start"}
    ]}
]

# ── HELPERS ──────────────────────────────────────────────────
def progress_bar(correct: int, wrong: int) -> str:
    filled = "█" * min(correct, BAR_LEN)
    empty  = "░" * (BAR_LEN - len(filled))
    return f"[{filled}{empty}]  ✅ {correct}/{WIN_AT}  ❌ {wrong}/{LOSE_AT}"

def build_question_blocks(q_idx: int, correct: int, wrong: int, step: int):
    q = QUESTIONS[q_idx]
    # full option text
    options_list_md = "\n".join(
        f"*{opt['id'].upper()}* – {opt['txt']}"
        for opt in q["options"]
    )
    # letter‐only buttons
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": opt["id"].upper()},
            "action_id": f"answer_{opt['id']}",
            "value": json.dumps({
                "q_idx": q_idx,
                "step": step,
                "c": correct,
                "w": wrong,
                "answer": opt["id"]
            })
        }
        for opt in q["options"]
    ]
    return [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"{progress_bar(correct, wrong)}\n*Q{step+1}:* {q['q']}"
         }},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": options_list_md}
        },
        {"type": "actions", "elements": buttons}
    ]

# ── SLASH COMMAND ────────────────────────────────────────────
@app.command("/cyberquest")
def start_quiz(ack, respond, command):
    ack()
    respond(blocks=start_ui, text="Ready for CyberQuest!")

# ── START BUTTON ────────────────────────────────────────────
@app.action("start_game_click")
def handle_start_click(ack, body, respond):
    ack()
    user = body["user"]["id"]
    # Build a shuffled queue of all question indices
    queue = list(range(len(QUESTIONS)))
    random.shuffle(queue)
    sessions[user] = {
        "queue": queue,
        "step": 0,
        "correct": 0,
        "wrong": 0
    }
    # Pull first question
    q_idx = queue[0]
    st = sessions[user]
    blocks = build_question_blocks(q_idx, 0, 0, 0)
    respond(replace_original=True, blocks=blocks, text=QUESTIONS[q_idx]["q"])

# ── ANSWER HANDLER ──────────────────────────────────────────
@app.action(re.compile(r"^answer_[a-z]$"))
def handle_answer(ack, body, respond):
    ack()
    user = body["user"]["id"]
    state = sessions.get(user)
    if not state:
        return respond(text="❗ No active game. Type `/cyberquest` to start.")

    data      = json.loads(body["actions"][0]["value"])
    q_idx     = data["q_idx"]
    step      = data["step"]
    correct   = data["c"]
    wrong     = data["w"]
    answer_id = data["answer"]

    q   = QUESTIONS[q_idx]
    opt = next(o for o in q["options"] if o["id"] == answer_id)

    # Update scores
    if opt["ok"]:
        correct += 1
    else:
        wrong += 1
    state["correct"], state["wrong"] = correct, wrong

    # Win/Lose?
    if correct >= WIN_AT:
        del sessions[user]
        return respond(replace_original=True,
                       text=f"🏆 You win! {correct}/{WIN_AT} correct. Type `/cyberquest` to play again.")
    if wrong >= LOSE_AT:
        del sessions[user]
        return respond(replace_original=True,
                       text=f"💀 Game over! {wrong}/{LOSE_AT} wrong. Type `/cyberquest` to try again.")

    # Show feedback + Next
    feedback = [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"*{'✅ Correct!' if opt['ok'] else '❌ Incorrect.'}*\n{opt['why']}"
         }},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Next ▶️"},
                "action_id": "next_click",
                "value": json.dumps({
                    "step": step,
                    "correct": correct,
                    "wrong": wrong
                })
            }
        ]}
    ]
    respond(replace_original=True, blocks=feedback)

# ── NEXT BUTTON ──────────────────────────────────────────────
@app.action("next_click")
def handle_next(ack, body, respond):
    ack()
    user = body["user"]["id"]
    state = sessions.get(user)
    if not state:
        return respond(text="❗ No active game. Type `/cyberquest` to start.")

    # Advance to the next step in the shuffled queue
    state["step"] += 1
    idx = state["step"]
    queue = state["queue"]
    # If we run out of questions, reshuffle or wrap
    if idx >= len(queue):
        random.shuffle(queue)
        state["step"] = 0
        idx = 0
    q_idx = queue[idx]

    # Build the next question
    blocks = build_question_blocks(
        q_idx,
        state["correct"],
        state["wrong"],
        state["step"]
    )
    respond(replace_original=True,
            blocks=blocks,
            text=QUESTIONS[q_idx]["q"])

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

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
