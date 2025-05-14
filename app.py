from flask import Flask, request, jsonify
import os, json, base64, re
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}                       # { user_id: {"session": gemini_chat , "score": int} }

# ──────────── 1. Google Gemini credentials ────────────
def get_google_credentials():
    b64 = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not b64:
        raise RuntimeError("GEMINI_SERVICE_ACCOUNT env var missing")
    info = json.loads(base64.b64decode(b64).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/generative-language"]
    )

genai.configure(credentials=get_google_credentials())

# ──────────── 2. per-user chat & score ────────────
def get_chat(uid: str):
    if uid not in chat_sessions:
        system_prompt = (
            "Welcome to *CyberQuest: Security Training!* "
            "End EVERY scenario with 2-4 lines that start with • (bullet)."
        )
        chat = genai.GenerativeModel("models/gemini-1.5-flash").start_chat(
            history=[{"role": "user", "parts": [system_prompt]}]
        )
        chat_sessions[uid] = {"session": chat, "score": 0}
    return chat_sessions[uid]["session"]

def gemini(prompt: str, uid: str) -> str:
    txt = get_chat(uid).send_message(prompt).text
    print("Gemini raw:", txt)            # visible in Render logs
    return txt

# ──────────── 3. helpers → Slack blocks ────────────
def format_body(txt: str) -> str:
    txt = txt.replace("**", "*").replace("##", "*").replace("  ", " ").replace(" - ", "• ")
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("•"):              # bullets become buttons
            continue
        if s.lower().startswith(("from:", "subject:")):
            s = f":email: *{s}*"
        out.append(s)
    return "\n".join(out).strip()

bullet = re.compile(r"^(?:•|\*|[A-Da-d]\)|\d+\))\s*(.+)$")   # also matches A) 1) etc.

def choices(txt: str, limit=35):
    cs = []
    for ln in txt.splitlines():
        m = bullet.match(ln.strip())
        if m:
            lbl = m.group(1).strip()
            if len(lbl) > limit:
                lbl = " ".join(lbl.split()[:6]) + "…"
            cs.append(lbl)
    return cs[:5] or ["Continue"]

def blocks(raw: str, score: int):
    body = format_body(raw)
    opts = choices(raw)
    return [
        {"type": "section",
         "text": {"type": "mrkdwn", "text": body or "_(no text)_"   }},
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": f"*Score:* {score}"}]},
        {"type": "actions",
         "elements": [
             {"type": "button",
              "text": {"type": "plain_text", "text": o},
              "value": o,
              "action_id": f"choice_{i}"}
             for i, o in enumerate(opts)
         ]}
    ]

# ──────────── 4. /cyberquest slash command ────────────
@app.route("/cyberquest", methods=["POST"])
def slash():
    txt = request.form.get("text", "").lower().strip()
    uid = request.form["user_id"]

    if txt in {"", "menu", "start"}:
        menu_blocks = {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Start Training"},
                 "value": "start", "action_id": "start"},
                {"type": "button", "text": {"type": "plain_text", "text": "How to Play"},
                 "value": "help", "action_id": "help"},
                {"type": "button", "text": {"type": "plain_text", "text": "Exit"},
                 "value": "exit", "action_id": "exit"}
            ]
        }
        return jsonify({
            "response_type": "ephemeral",          # must be present for slash reply
            "text": "fallback",
            "blocks": [
                {"type": "section",
                 "text": {"type": "mrkdwn", "text": "*CyberQuest* — choose an option:"}},
                menu_blocks
            ]
        })

    # free-text sent directly to Gemini
    raw = gemini(txt, uid)
    return jsonify({
        "response_type": "ephemeral",
        "text": "fallback",
        "blocks": blocks(raw, chat_sessions.get(uid, {}).get("score", 0))
    })

# ──────────── 5. interactive button clicks ────────────
@app.route("/slack/interactive", methods=["POST"])
def interactive():
    data   = json.loads(request.form["payload"])
    uid    = data["user"]["id"]
    choice = data["actions"][0]["value"]

    get_chat(uid)        # ensure session exists

    # menu handlers
    if choice == "start":
        chat_sessions[uid]["score"] = 0
        raw = gemini("start training", uid)
    elif choice == "help":
        raw = ("Each scenario is private (ephemeral). Click a button to act. "
               "Good security choices raise your score.")
    elif choice == "exit":
        raw = "Exited CyberQuest. Use `/cyberquest start` to return."
    else:
        raw = gemini(choice, uid)
        if "report" in choice.lower():
            chat_sessions[uid]["score"] += 1
        elif any(k in choice.lower() for k in ("click", "open")):
            chat_sessions[uid]["score"] -= 1

    # update the original bot message in-place
    return jsonify({
        "replace_original": True,
        "text": "fallback",
        "blocks": blocks(raw, chat_sessions[uid]["score"])
    })

# ──────────── 6. local run ────────────
if __name__ == "__main__":
    app.run(debug=True)
