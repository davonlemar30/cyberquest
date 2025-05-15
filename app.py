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
                """
    You are running a corporate-style security training called CyberQuest for Microcom employees.
    Each response must contain **exactly one** realistic scenario.  
    After that scenario’s text and 3–4 bullet-choices, stop.  
    Do not list any additional scenarios.  
    Wait for the user to request “Next Scenario” before continuing.
    """
        )
        sess = genai.GenerativeModel("models/gemini-1.5-flash")\
                  .start_chat(history=[{"role":"user","parts":[system]}])
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
    txt = txt.replace("**","*").replace(" - ","• ")
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("•"): 
            continue
        if s.lower().startswith(("from:","subject:")):
            s = f":email: *{s}*"
        out.append(s)
    return "\n".join(out).strip()

bullet_re = re.compile(r"^(?:•|\*|[A-Da-d]\)|\d+\))\s*(.+)$")
def extract_choices(txt: str, limit=35):
    cs = []
    for ln in txt.splitlines():
        m = bullet_re.match(ln.strip())
        if m:
            lbl = m.group(1).strip()
            if len(lbl) > limit:
                lbl = " ".join(lbl.split()[:6]) + "…"
            cs.append(lbl)
    return cs[:5] or ["Continue"]

def build_blocks(raw: str, score: int):
    body = format_body(raw) or "_(no text)_"
    opts = extract_choices(raw)
    blocks = [
        {"type":"section","text":{"type":"mrkdwn","text":body}},
        {"type":"context","elements":[{"type":"mrkdwn","text":f"*Score:* {score}"}]},
        {"type":"actions","elements":[
            {
              "type":"button",
              "text":{"type":"plain_text","text":o},
              "value":o,
              "action_id":f"choice_{i}"
            } for i,o in enumerate(opts)
        ]}
    ]
    return blocks

# ─────────────────────────────────────────
# 4. Slash Command Handler
# ─────────────────────────────────────────
@app.route("/cyberquest", methods=["POST"])
def slash():
    uid = request.form["user_id"]
    cmd = request.form.get("text","").strip().lower()

    # show main menu
    if cmd in ("", "menu", "start"):
        menu = {
            "type":"actions","elements":[
                {"type":"button","text":{"type":"plain_text","text":"Start Training"},
                 "value":"start","action_id":"start"},
                {"type":"button","text":{"type":"plain_text","text":"How to Play"},
                 "value":"help","action_id":"help"},
                {"type":"button","text":{"type":"plain_text","text":"Exit"},
                 "value":"exit","action_id":"exit"}
            ]
        }
        return jsonify({
            "response_type":"ephemeral",
            "text":"_",               # fallback
            "blocks":[
              {"type":"section","text":{"type":"mrkdwn","text":"*CyberQuest* — choose an option:"}},
              menu
            ]
        })

    # otherwise free‐text into Gemini
    raw = ask_gemini(cmd, uid)
    blocks = build_blocks(raw, chat_sessions.get(uid,{}).get("score",0))
    return jsonify({
        "response_type":"ephemeral",
        "text":"_",
        "blocks": blocks
    })

# ─────────────────────────────────────────
# 5. Interactive Button Clicks
# ─────────────────────────────────────────
@app.route("/slack/interactive", methods=["POST"])
def interactive():
    payload = json.loads(request.form["payload"])
    uid      = payload["user"]["id"]
    choice   = payload["actions"][0]["value"]
    resp_url = payload["response_url"]

    # ensure session exists
    get_chat(uid)

    # handle menu buttons
    if choice == "start":
        chat_sessions[uid]["score"] = 0
        raw = ask_gemini("start training", uid)
    elif choice == "help":
        raw = (
          "CyberQuest is private to you.  "
          "Each scenario ends with bullet actions.  "
          "Good choices up your score."
        )
    elif choice == "exit":
        raw = "You’ve exited CyberQuest.  Use `/cyberquest start` to re-enter."
    else:
        # pass your choice back into Gemini
        raw = ask_gemini(choice, uid)
        # scoring: report=+1, click/open=–1
        if "report" in choice.lower():
            chat_sessions[uid]["score"] += 1
        elif any(k in choice.lower() for k in ("click","open")):
            chat_sessions[uid]["score"] -= 1

    blocks = build_blocks(raw, chat_sessions[uid]["score"])

    # **Use response_url** to update this ephemeral message
    requests.post(resp_url, json={
        "response_type":    "ephemeral",
        "replace_original": True,
        "blocks":           blocks
    })

    # Acknowledge to Slack
    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
