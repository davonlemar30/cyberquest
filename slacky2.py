import os
import json
import re
import random
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from cyberquestadv import handle_adventure_start, handle_adventure_choice

# ── LOAD QUESTIONS ───────────────────────────────────────────
QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.json")
with open(QUESTIONS_PATH, "r") as f:
    QUESTIONS = json.load(f)

# ── CONFIG ───────────────────────────────────────────────────
WIN_AT = int(os.getenv("WIN_AT", 10))
LOSE_AT = int(os.getenv("LOSE_AT", 5))
BAR_LEN = int(os.getenv("BAR_LEN", 10))
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

# ── APP INIT ─────────────────────────────────────────────────
app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# ── IN-MEMORY SESSION STORE ─────────────────────────────────
# user_id → { queue: [...], step: int, correct: int, wrong: int }
sessions: dict[str, dict] = {}

# ── INTRO UI ─────────────────────────────────────────────────
start_ui = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*🎮 Welcome to CyberQuest!*\n\n"
                f"First to *{WIN_AT}* correct wins. First to *{LOSE_AT}* wrong loses.\n\n"
                "*Think you're too smart to get phished? Think again.*\n"
                "Every right answer gets you closer to victory.\n"
                "Every wrong answer? Closer to being hacked 😬\n\n"
                "Choose a mode to begin:"
            )
        }
    },
    {"type": "divider"},
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🧠 Start Quiz", "emoji": True},
                "action_id": "start_game_click",
                "value": "start"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🚨 Start Adventure (Coming Soon)", "emoji": True},
                "action_id": "start_adventure_click",
                "value": "coming_soon",
                "style": "danger"
            }
        ]
    }
]

# ── HELPERS ──────────────────────────────────────────────────


def progress_bar(correct: int, wrong: int) -> str:
    filled = "█" * min(correct, BAR_LEN)
    empty = "░" * (BAR_LEN - len(filled))
    return f"[{filled}{empty}]  ✅ {correct}/{WIN_AT}  ❌ {wrong}/{LOSE_AT}"


def build_question_blocks(q_idx: int, correct: int, wrong: int, step: int):
    q = QUESTIONS[q_idx]
    opts = q["options"].copy()
    random.shuffle(opts)
    letters = ["A", "B", "C", "D"]

    options_md = "\n".join(
        f"*{letters[i]}* – {opt['txt']}" for i, opt in enumerate(opts))
    buttons = []
    for i, opt in enumerate(opts):
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": letters[i]},
            "action_id": f"answer_{letters[i]}",
            "value": json.dumps({
                "q_idx":      q_idx,
                "step":       step,
                "c":          correct,
                "w":          wrong,
                "choice_idx": i,
                "orig_id":    opt["id"]
            })
        })

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{progress_bar(correct, wrong)}\n*Q{step+1}:* {q['q']}"
            }
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": options_md}
        },
        {
            "type": "actions",
            "elements": buttons
        }
    ]

# ── SLASH COMMAND ────────────────────────────────────────────


@app.command("/cyberquest")
def start_quiz(ack, respond, command):
    ack()
    respond(blocks=start_ui, text="Ready for CyberQuest!")

# ── START QUIZ BUTTON ────────────────────────────────────────


@app.action("start_game_click")
def handle_start_click(ack, body, respond):
    ack()
    user = body["user"]["id"]
    queue = list(range(len(QUESTIONS)))
    random.shuffle(queue)
    sessions[user] = {"queue": queue, "step": 0, "correct": 0, "wrong": 0}

    q_idx = queue[0]
    blocks = build_question_blocks(q_idx, 0, 0, 0)
    respond(
        replace_original=True,
        blocks=blocks,
        text=QUESTIONS[q_idx]["q"]
    )

# ── ANSWER HANDLER ──────────────────────────────────────────


@app.action(re.compile(r"^answer_[A-D]$"))
def handle_answer(ack, body, respond):
    ack()
    user = body["user"]["id"]
    state = sessions.get(user)
    if not state:
        return respond(text="❗ No active game. Type `/cyberquest` to start.")

    data = json.loads(body["actions"][0]["value"])
    q_idx = data["q_idx"]
    step = data["step"]
    correct = data["c"]
    wrong = data["w"]
    orig_id = data["orig_id"]

    q = QUESTIONS[q_idx]
    opt = next(o for o in q["options"] if o["id"] == orig_id)

    if opt["ok"]:
        correct += 1
        feedback_emoji = "🟢"
        feedback_text = "*Correct!*"
    else:
        wrong += 1
        feedback_emoji = "🔴"
        feedback_text = "*Incorrect.*"

    sessions[user]["correct"] = correct
    sessions[user]["wrong"] = wrong

    if correct >= WIN_AT:
        del sessions[user]
        return respond(
            replace_original=True,
            text=f"🏆 You win! {correct}/{WIN_AT} correct. Type `/cyberquest` to play again."
        )
    if wrong >= LOSE_AT:
        del sessions[user]
        return respond(
            replace_original=True,
            text=f"💀 Game over! {wrong}/{LOSE_AT} wrong. Type `/cyberquest` to try again."
        )

    feedback_blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{feedback_emoji} {feedback_text}\n{opt['why']}"}
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Next ▶️"},
                    "action_id": "next_click",
                    "value": json.dumps({"step": step})
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
        return respond(text="❗ No active game. Type `/cyberquest` to start.")

    state["step"] += 1
    idx = state["step"]
    queue = state["queue"]
    if idx >= len(queue):
        random.shuffle(queue)
        state["step"], idx = 0, 0
    q_idx = queue[idx]

    blocks = build_question_blocks(
        q_idx,
        state["correct"],
        state["wrong"],
        state["step"]
    )
    respond(
        replace_original=True,
        blocks=blocks,
        text=QUESTIONS[q_idx]["q"]
    )


# ── ADVENTURE MODE ──────────────────────────────────────────
MY_USER_ID = "U06N9F2BV4P"  # your Slack user ID here


@app.action("start_adventure_click")
def start_adventure_click(ack, body, respond, client):
    ack()
    user_id = body["user"]["id"]

    # fetch the user's Slack display name
    profile = client.users_info(user=user_id)["user"]["profile"]
    display_name = profile.get("display_name") or profile.get(
        "real_name") or "Player"

    if user_id != MY_USER_ID:
        return respond(
            text="🛠️ *Adventure Mode is coming soon!* Stay tuned for a more immersive training experience.",
            replace_original=False
        )

    # launch the adventure for you
    blocks = handle_adventure_start(user_id, display_name)
    respond(replace_original=True, blocks=blocks)


# ── ADVENTURE CHOICE HANDLER ─────────────────────────────────
# note: regex is r"^adv_\d+$", not with a double backslash
@app.action("adv_0")
def handle_adventure_choice_action(ack, body, client, logger):
    ack()  # ✅ This tells Slack you received the interaction

    user_id = body["user"]["id"]
    value = body["actions"][0]["value"]

    blocks = handle_adventure_choice(None, value)

    try:
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks
        )
    except Exception as e:
        logger.error(f"Error updating message: {e}")


# ── FLASK ROUTES & HEALTH ───────────────────────────────────
@flask_app.route("/slack/commands", methods=["POST"])
def slack_commands():
    return handler.handle(request)


@flask_app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    return handler.handle(request)


@flask_app.route("/", methods=["GET"])
def health():
    return "🟢 CyberQuest is alive", 200


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
