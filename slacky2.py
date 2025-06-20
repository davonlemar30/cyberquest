# ─────────────────────────────────────────────────────────────
#  CyberQuest – simple, non-AI quiz for Slack
#  Requirements: slack-bolt, Flask
#  Invite the bot to any channel before running /cyberquest
# ─────────────────────────────────────────────────────────────
import os, json, re
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
from random import shuffle

# ── CONFIG ───────────────────────────────────────────────────
WIN_AT  = int(os.getenv("WIN_AT", 10))
LOSE_AT = int(os.getenv("LOSE_AT", 5))
BAR_LEN = int(os.getenv("BAR_LEN", 10))

SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

# ── LOAD QUESTIONS ──────────────────────────────────────────
with open(os.path.join(os.path.dirname(__file__), "questions.json"), "r") as f:
    QUESTIONS = json.load(f)

# ── INIT APP + FLASK ADAPTER ─────────────────────────────────
app        = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
flask_app  = Flask(__name__)
handler    = SlackRequestHandler(app)

# ── HELPERS ─────────────────────────────────────────────────
def progress_bar(correct: int, wrong: int) -> str:
    filled = "█" * min(correct, BAR_LEN)
    empty  = "░" * (BAR_LEN - len(filled))
    return f"[{filled}{empty}]  ✅ {correct}/{WIN_AT}  ❌ {wrong}/{LOSE_AT}"

def build_question_blocks(q_idx: int, correct: int, wrong: int):
    q = QUESTIONS[q_idx % len(QUESTIONS)]
    shuffle(q["options"])  # randomize order each time
    header = progress_bar(correct, wrong)

    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"{opt['id'].upper()}) {opt['txt']}"},
            "action_id": f"answer_{opt['id']}",             # ← unique per button
            "value": json.dumps({"q": q_idx,
                                 "answer": opt['id'],
                                 "c": correct,
                                 "w": wrong})
        }
        for opt in q["options"]
    ]

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"{header}\n*Q{q_idx + 1}:* {q['q']}"}
        },
        {"type": "actions", "elements": buttons}
    ]

# ── SLASH COMMAND ───────────────────────────────────────────
@app.command("/cyberquest")
def start_quiz(ack, body):
    channel = body["channel_id"]
    blocks  = build_question_blocks(0, 0, 0)
    ack()  # acknowledge immediately
    app.client.chat_postMessage(channel=channel,
                                blocks=blocks,
                                text=QUESTIONS[0]["q"])

# ── ANSWER BUTTONS (regex catches answer_a / answer_b …) ────
@app.action(re.compile(r"^answer_[a-z]$"))
def handle_answer(ack, body, respond):
    ack()
    data      = json.loads(body["actions"][0]["value"])
    q_idx     = int(data["q"])
    answer_id = data["answer"]
    correct   = int(data["c"])
    wrong     = int(data["w"])

    q   = QUESTIONS[q_idx % len(QUESTIONS)]
    opt = next(o for o in q["options"] if o["id"] == answer_id)

    correct += 1 if opt["ok"] else 0
    wrong   += 1 if not opt["ok"] else 0

    # Win / lose checks
    if correct >= WIN_AT:
        return respond(replace_original=True,
                       text=f"🏆 *You win!* {correct} correct answers.")
    if wrong >= LOSE_AT:
        return respond(replace_original=True,
                       text=f"💀 *Game over!* {wrong} wrong answers.")

    feedback_blocks = [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"*{'✅ Correct!' if opt['ok'] else '❌ Incorrect.'}*\n{opt['why']}"}},
        {"type": "actions",
         "elements": [{
             "type": "button",
             "text": {"type": "plain_text", "text": "Next ▶️"},
             "action_id": "next_click",
             "value": json.dumps({"next": q_idx + 1, "c": correct, "w": wrong})
         }]}
    ]
    respond(replace_original=True, blocks=feedback_blocks)

# ── NEXT BUTTON ─────────────────────────────────────────────
@app.action("next_click")
def handle_next(ack, body, respond):
    ack()
    data    = json.loads(body["actions"][0]["value"])
    q_idx   = int(data["next"])
    correct = int(data["c"])
    wrong   = int(data["w"])

    blocks = build_question_blocks(q_idx, correct, wrong)
    respond(replace_original=True,
            blocks=blocks,
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

# ── LOCAL RUN ───────────────────────────────────────────────
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
