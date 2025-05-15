from flask import Flask, request, jsonify
import os, json, base64, re
import requests
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}  # { user_id: {"session": gemini_chat, "score": int} }

# ─────────────────────────────────────────
# 1. Configure Gemini
# ─────────────────────────────────────────
def get_google_credentials():
    b64 = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not b64:
        raise RuntimeError("Missing GEMINI_SERVICE_ACCOUNT")
    info = json.loads(base64.b64decode(b64).decode())
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/generative-language"]
    )

genai.configure(credentials=get_google_credentials())

# ─────────────────────────────────────────
# 2. Per-user chat + score
# ─────────────────────────────────────────
def get_chat(uid: str):
    if uid not in chat_sessions:
        system = (
            "You are running a corporate-style security training called CyberQuest for Microcom employees.\n"
            "Each response must contain exactly one realistic scenario, then **four** lettered options:\n"
            "A) …\nB) …\nC) …\nD) …\n"
            "Then stop and wait for user to pick A, B, C, or D.\n"
            "After they click, you will reply “Correct” or “Incorrect” and only then proceed on “Next Scenario.”"
        )
        sess = genai.GenerativeModel("models/gemini-1.5-flash") \
                    .start_chat(history=[{"role": "user", "parts": [system]}])
        chat_sessions[uid] = {"session": sess, "score": 0}
    return chat_sessions[uid]["session"]

def ask_gemini(prompt: str, uid: str) -> str:
    txt = get_chat(uid).send_message(prompt).text
    print("Gemini raw:", txt)  # for Render logs
    return txt

# ─────────────────────────────────────────
# 3. Helpers → Slack Blocks
# ─────────────────────────────────────────
def format_body(txt: str) -> str:
    # leave A)/B)/C)/D) lines in place; skip any stray bullets
    out = []
    for ln in txt.splitlines():
        s = ln.rstrip()
        # skip stray bullets
        if s.startswith("•"):
            continue
        if s.lower().startswith(("from:", "subject:")):
            s = f":email: *{s}*"
        out.append(s)
    return "\n".join(out).strip() or "_(no text)_"

# match “A) text”
LETTER_RE = re.compile(r"^([A-D])\)\s*(.+)$")

def extract_choices(txt: str):
    cs = []
    for ln in txt.splitlines():
        m = LETTER_RE.match(ln.strip())
        if m:
            letter, label = m.groups()
            cs.append((letter, label.strip()))
    # fallback if none found
    return cs or [("A", "Continue")]

def build_blocks(raw: str, score: int):
    body = format_body(raw)
    choices = extract_choices(raw)

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"*Score:* {score}"}
        ]},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": letter},
                "value": letter,
                "action_id": f"choice_{letter}"
            }
            for letter, _ in choices
        ]}
    ]
    return blocks

# ─────────────────────────────────────────
# 4. Slash Command Handler
# ─────────────────────────────────────────
@app.route("/cyberquest", methods=["POST"])
def slash():
    uid = request.form["user_id"]
    cmd = request.form.get("text", "").strip().lower()

    # show main menu
    if cmd in ("", "menu", "start"):
        menu = {
            "type": "actions", "elements": [
                {"type":"button","text":{"type":"plain_text","text":"Start Training"},
                 "value":"start","action_id":"start"},
                {"type":"button","text":{"type":"plain_text","text":"How to Play"},
                 "value":"help","action_id":"help"},
                {"type":"button","text":{"type":"plain_text","text":"Exit"},
                 "value":"exit","action_id":"exit"}
            ]
        }
        return jsonify({
            "response_type": "ephemeral",
            "text": "_",  # fallback
            "blocks": [
                {"type":"section","text":{"type":"mrkdwn",
                 "text":"*CyberQuest* — choose an option:"}},
                menu
            ]
        })

    # free-text into Gemini for custom prompts
    raw = ask_gemini(cmd, uid)
    blocks = build_blocks(raw, chat_sessions[uid]["score"])
    return jsonify({
        "response_type": "ephemeral",
        "text": "_",
        "replace_original": False,
        "blocks": blocks
    })

# ─────────────────────────────────────────
# 5. Interactive Button Clicks
# ─────────────────────────────────────────
@app.route("/slack/interactive", methods=["POST"])
def interactive():
    payload = json.loads(request.form["payload"])
    uid     = payload["user"]["id"]
    choice  = payload["actions"][0]["value"]
    resp_url = payload["response_url"]

    # ensure session exists
    get_chat(uid)

    # handle menu
    if choice == "start":
        chat_sessions[uid]["score"] = 0
        raw = ask_gemini("start training", uid)
    elif choice == "help":
        raw = (
            "CyberQuest is completely private (ephemeral).  "
            "Each scenario ends in A), B), C), D).  "
            "Click your letter to respond; correct answers raise your score."
        )
    elif choice == "exit":
        raw = "You’ve exited CyberQuest.  Use `/cyberquest start` to return anytime."
    else:
        # send letter back to Gemini
        raw = ask_gemini(f"I choose {choice}", uid)
        # bump score if Gemini says “Correct”
        if raw.lower().startswith("correct"):
            chat_sessions[uid]["score"] += 1

    blocks = build_blocks(raw, chat_sessions[uid]["score"])

    # update the ephemeral message in-place
    requests.post(resp_url, json={
        "response_type":    "ephemeral",
        "replace_original": True,
        "blocks":           blocks
    })

    # immediate 200 OK ack
    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
