from flask import Flask, request, jsonify
import os, json, base64, re
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}          # { user_id: {"session": gemini_chat , "score": int} }

# ─────────────────── 1. Google Gemini creds ───────────────────
def get_google_credentials():
    b64 = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not b64:
        raise RuntimeError("GEMINI_SERVICE_ACCOUNT env var missing")
    info = json.loads(base64.b64decode(b64).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/generative-language"]
    )

genai.configure(credentials=get_google_credentials())

# ─────────────────── 2. per-user chat & score ──────────────────
def get_chat_session(uid: str):
    if uid not in chat_sessions:
        system_prompt = (
            "Welcome to *CyberQuest: Security Training!* "
            "Finish EVERY scenario with 2-4 lines that start with the bullet character • "
            "(example:  '• Report to IT').  Do NOT use A) B) 1) — only •."
        )
        chat = genai.GenerativeModel("models/gemini-1.5-flash").start_chat(
            history=[{"role": "user", "parts": [system_prompt]}]
        )
        chat_sessions[uid] = {"session": chat, "score": 0}
    return chat_sessions[uid]["session"]

def gemini_reply(prompt: str, uid: str) -> str:
    resp = get_chat_session(uid).send_message(prompt)
    print("Gemini raw:", resp.text)   # appears in Render logs
    return resp.text

# ─────────────────── 3. helpers ────────────────────────────────
def format_scenario(txt: str) -> str:
    txt = txt.replace("**", "*").replace("##", "*").replace("  ", " ").replace(" - ", "• ")
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("•"):                   # bullets become buttons
            continue
        if s.lower().startswith(("from:", "subject:")):
            s = f":email: *{s}*"
        out.append(s)
    return "\n".join(out).strip()

bullet_pat = re.compile(r"^(?:•|\*|[A-Da-d]\)|\d+\))\s*(.+)$")   # accept • or A)/1)

def extract_choices(txt: str, limit=40):
    choices = []
    for ln in txt.splitlines():
        m = bullet_pat.match(ln.strip())
        if not m:
            continue
        lbl = m.group(1).strip()
        if len(lbl) > limit:
            lbl = " ".join(lbl.split()[:6]) + "…"
        choices.append(lbl)
    return choices[:5] if choices else ["Continue"]

def build_blocks(raw: str, score: int):
    scenario = format_scenario(raw)
    buttons  = extract_choices(raw)

    blocks = [
        {"type":"section",
         "text":{"type":"mrkdwn","text": scenario or "_(no text)_" }},
        {"type":"context",
         "elements":[{"type":"mrkdwn","text":f"*Score:* {score}"}]},
        {"type":"actions",
         "elements":[
             {"type":"button",
              "text":{"type":"plain_text","text":b},
              "value":b,
              "action_id":f"choice_{i}"}
             for i, b in enumerate(buttons)
         ]}
    ]
    return blocks

# ─────────────────── 4. /cyberquest slash cmd ─────────────────
@app.route("/cyberquest", methods=["POST"])
def slash():
    cmd = request.form.get("text","").lower().strip()
    uid = request.form["user_id"]

    if cmd in {"", "menu", "start"}:
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
            "text":" ",                     # ← REQUIRED fallback
            "blocks":[
                {"type":"section",
                 "text":{"type":"mrkdwn","text":"*CyberQuest* — choose an option:"}},
                menu
            ]
        })

    # free-text scenario
    raw = gemini_reply(cmd, uid)
    blocks = build_blocks(raw, chat_sessions.get(uid,{}).get("score",0))
    return jsonify({"response_type":"ephemeral","text":" ","blocks":blocks})

# ─────────────────── 5. button clicks ─────────────────────────
@app.route("/slack/interactive", methods=["POST"])
def interactive():
    data   = json.loads(request.form["payload"])
    uid    = data["user"]["id"]
    choice = data["actions"][0]["value"]

    get_chat_session(uid)                         # ensure session

    if choice == "start":
        chat_sessions[uid]["score"] = 0
        raw = gemini_reply("start training", uid)
    elif choice == "help":
        raw = ("Each scenario is *private* to you. Click a button to act. "
               "Good security choices raise your score.")
    elif choice == "exit":
        raw = "Exited CyberQuest. Use `/cyberquest start` to return."
    else:
        raw = gemini_reply(choice, uid)
        # simple score logic
        if "report" in choice.lower():
            chat_sessions[uid]["score"] += 1
        elif any(k in choice.lower() for k in ("click", "open")):
            chat_sessions[uid]["score"] -= 1

    blocks = build_blocks(raw, chat_sessions[uid]["score"])
    return jsonify({"response_type":"ephemeral","text":" ","blocks":blocks})

# ─────────────────── 6. run local ─────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
