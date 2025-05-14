from flask import Flask, request, jsonify
import os
import json
import base64
import re
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}  # { user_id: {"session": gemini_chat, "score": int} }

# ──────────── 1. Google Gemini credentials ────────────
def get_google_credentials():
    b64 = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not b64:
        raise RuntimeError("GEMINI_SERVICE_ACCOUNT env var missing")
    info = json.loads(base64.b64decode(b64).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/generative-language"]
    )

genai.configure(credentials=get_google_credentials())

# ──────────── 2. Per-user chat & score ────────────
def get_chat(uid: str):
    if uid not in chat_sessions:
        system_prompt = (
            "Welcome to *CyberQuest: Security Training!* "
            "End EVERY scenario with 2–4 lines starting with • (the bullet)."
        )
        session = genai.GenerativeModel("models/gemini-1.5-flash").start_chat(
            history=[{"role":"user", "parts":[system_prompt]}]
        )
        chat_sessions[uid] = {"session": session, "score": 0}
    return chat_sessions[uid]["session"]

def gemini(prompt: str, uid: str) -> str:
    txt = get_chat(uid).send_message(prompt).text
    print("Gemini raw:", txt)  # for Render logs
    return txt

# ──────────── 3. Helpers → Slack blocks ────────────
def format_body(txt: str) -> str:
    txt = txt.replace("**","*").replace("##","*").replace("  "," ").replace(" - ","• ")
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("•"):
            continue  # bullets → buttons only
        if s.lower().startswith(("from:","subject:")):
            s = f":email: *{s}*"
        out.append(s)
    return "\n".join(out).strip()

bullet_rx = re.compile(r"^(?:•|\*|[A-Da-d]\)|\d+\))\s*(.+)$")
def extract_choices(txt: str, limit=35):
    cs = []
    for ln in txt.splitlines():
        m = bullet_rx.match(ln.strip())
        if m:
            lbl = m.group(1).strip()
            if len(lbl) > limit:
                lbl = " ".join(lbl.split()[:6]) + "…"
            cs.append(lbl)
    return cs[:5] or ["Continue"]

def build_blocks(raw: str, score: int):
    body = format_body(raw) or "_(no text)_"
    choices = extract_choices(raw)
    blocks = [
        {"type":"section","text":{"type":"mrkdwn","text": body }},
        {"type":"context","elements":[{"type":"mrkdwn","text":f"*Score:* {score}"}]},
        {
            "type":"actions",
            "elements":[
                {
                    "type":"button",
                    "text":{"type":"plain_text","text":opt},
                    "value":opt,
                    "action_id":f"choice_{i}"
                }
                for i,opt in enumerate(choices)
            ]
        }
    ]
    return blocks

# ──────────── 4. Slash command /cyberquest ────────────
@app.route("/cyberquest", methods=["POST"])
def slash():
    txt = request.form.get("text", "").lower().strip()
    uid = request.form["user_id"]

    # Main menu
    if txt in {"", "menu", "start"}:
        menu = {
            "type":"actions",
            "elements":[
                {"type":"button","text":{"type":"plain_text","text":"Start Training"},
                 "value":"start","action_id":"start"},
                {"type":"button","text":{"type":"plain_text","text":"How to Play"},
                 "value":"help","action_id":"help"},
                {"type":"button","text":{"type":"plain_text","text":"Exit"},
                 "value":"exit","action_id":"exit"}
            ]
        }
        return jsonify({
            "replace_original": True,
            "text": "fallback",
            "blocks": [
                {"type":"section","text":{"type":"mrkdwn","text":"*CyberQuest* — choose an option:"}},
                menu
            ]
        })

    # Otherwise treat the text as a scenario prompt
    raw = gemini(txt, uid)
    return jsonify({
        "replace_original": True,
        "text": "fallback",
        "blocks": build_blocks(raw, chat_sessions.get(uid,{}).get("score",0))
    })

# ──────────── 5. Interactive button clicks ────────────
@app.route("/slack/interactive", methods=["POST"])
def interactive():
    data = json.loads(request.form["payload"])
    uid = data["user"]["id"]
    choice = data["actions"][0]["value"]

    # Ensure session exists
    get_chat(uid)

    # Menu handling
    if choice == "start":
        chat_sessions[uid]["score"] = 0
        raw = gemini("start training", uid)
    elif choice == "help":
        raw = (
            "CyberQuest runs *privately* (only you see it). "
            "Each scenario ends with bullet-button actions. "
            "Good choices raise your score."
        )
    elif choice == "exit":
        raw = "Exited CyberQuest. Use `/cyberquest start` to return."
    else:
        # Scenario choice
        raw = gemini(choice, uid)
        if "report" in choice.lower():
            chat_sessions[uid]["score"] += 1
        elif any(k in choice.lower() for k in ("click","open")):
            chat_sessions[uid]["score"] -= 1

    return jsonify({
        "replace_original": True,
        "text": "fallback",
        "blocks": build_blocks(raw, chat_sessions[uid]["score"])
    })

if __name__ == "__main__":
    app.run(debug=True)
