# ─────→  slacky.py  ←──────────────────────────────────────────
import os, json
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request

# ── ENV - VARS ────────────────────────────────────────────────
SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)

# ── CYBERQUEST CONFIG ────────────────────────────────────────
WIN_AT   = 10   # first to 10 correct
LOSE_AT  = 5    # first to 5 wrong
BAR_LEN  = 10   # width of progress bar

# TODO: paste your real question bank here
QUESTIONS = [
    {
        "q": "Sample question — replace me.",
        "options": [
            {"id": "a", "txt": "Choice A", "ok": True,
             "why": "Because A is correct."},
            {"id": "b", "txt": "Choice B", "ok": False,
             "why": "B is wrong."},
            {"id": "c", "txt": "Choice C", "ok": False, "why": "C is wrong."},
            {"id": "d", "txt": "Choice D", "ok": False, "why": "D is wrong."},
        ]
    },
    # …add as many scenarios as you like
]

# ── HELPERS ──────────────────────────────────────────────────
def progress_bar(correct, wrong):
    filled = "█" * min(correct, BAR_LEN)
    empty  = "░" * (BAR_LEN - len(filled))
    return f"[{filled}{empty}]  ✅ {correct}/{WIN_AT}  ❌ {wrong}/{LOSE_AT}"

def build_question_blocks(q_idx, correct, wrong):
    q = QUESTIONS[q_idx % len(QUESTIONS)]
    header = progress_bar(correct, wrong)

    question_block = {
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f"{header}\n*Q{q_idx+1}:* {q['q']}"}
    }
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text",
                     "text": f"{opt['id'].upper()}) {opt['txt']}"},
            "action_id": "answer_click",
            "value": json.dumps({
                "q": q_idx,
                "answer": opt["id"],
                "c": correct,
                "w": wrong
            })
        }
        for opt in q["options"]
    ]
    return [question_block, {"type": "actions", "elements": buttons}]

# ── SLASH COMMAND ────────────────────────────────────────────
@app.command("/cyberquest")
def start_quiz(ack, body):
    ack()
    blocks = build_question_blocks(0, 0, 0)
    app.client.chat_postMessage(channel=body["channel_id"],
                                blocks=blocks,
                                text=QUESTIONS[0]["q"])

# ── ANSWER CLICK ─────────────────────────────────────────────
@app.action("answer_click")
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

    # WIN / LOSE
    if correct >= WIN_AT:
        respond(replace_original=True,
                text=f"🏆 *You win!* {correct} correct answers.")
        return
    if wrong >= LOSE_AT:
        respond(replace_original=True,
                text=f"💀 *Game over!* {wrong} wrong answers.")
        return

    feedback_blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"*{'✅ Correct!' if opt['ok'] else '❌ Incorrect.'}*\n{opt['why']}"}
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Next ▶️"},
                    "action_id": "next_click",
                    "value": json.dumps({
                        "next": q_idx + 1,
                        "c": correct,
                        "w": wrong
                    })
                }
            ]
        }
    ]
    respond(replace_original=True, blocks=feedback_blocks)

# ── NEXT CLICK ───────────────────────────────────────────────
@app.action("next_click")
def handle_next(ack, body, respond):
    ack()
    data      = json.loads(body["actions"][0]["value"])
    q_idx     = int(data["next"])
    correct   = int(data["c"])
    wrong     = int(data["w"])

    blocks = build_question_blocks(q_idx, correct, wrong)
    respond(replace_original=True,
            blocks=blocks,
            text=QUESTIONS[q_idx % len(QUESTIONS)]["q"])

# ── FLASK ADAPTER ────────────────────────────────────────────
flask_app = Flask(__name__)
handler   = SlackRequestHandler(app)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

@flask_app.route("/slack/interactive", methods=["POST"])
def slack_interactive():
    return handler.handle(request)

@flask_app.route("/slack/commands", methods=["POST"])
def slack_commands():
    return handler.handle(request)

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
