from flask import Flask, request, jsonify
import os, json, base64, re
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}            # user_id → {"session": gemini_chat, "score": int}

# ─── 1. Google Gemini credentials ─────────────────────────────
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

# ─── 2. per-user chat + score ─────────────────────────────────
def get_chat_session(uid: str):
    if uid not in chat_sessions:
        prompt = ("Welcome to *CyberQuest: Security Training!* "
                  "Finish EVERY scenario with 2-4 bullet (•) choices.")
        chat = genai.GenerativeModel(
            "models/gemini-1.5-flash").start_chat(history=[{"role":"user","parts":[prompt]}])
        chat_sessions[uid] = {"session": chat, "score": 0}
    return chat_sessions[uid]["session"]

def gemini_reply(text: str, uid: str) -> str:
    resp = get_chat_session(uid).send_message(text)
    print("Gemini raw:", resp.text)
    return resp.text

# ─── 3. Slack block helpers ───────────────────────────────────
bullet_pat = re.compile(r"^(?:•|\*|[A-Da-d]\)|\d+\))\s*(.+)$")

def extract_choices(txt, limit=40):
    out=[]
    for ln in txt.splitlines():
        m = bullet_pat.match(ln.strip())
        if m:
            lbl=m.group(1).strip()
            if len(lbl)>limit:
                lbl=" ".join(lbl.split()[:6])+"…"
            out.append(lbl)
    return out[:5] or ["Continue"]

def format_scenario(txt):
    txt = txt.replace("**","*").replace("##","*").replace("  "," ").replace(" - ","• ")
    lines=[]
    for ln in txt.splitlines():
        s=ln.strip()
        if s.startswith("•"): continue
        if s.lower().startswith(("from:","subject:")): s=f":email: *{s}*"
        lines.append(s)
    return "\n".join(lines).strip()

def build_blocks(raw, score):
    scen=format_scenario(raw)
    choices=extract_choices(raw)
    blocks=[
        {"type":"section","text":{"type":"mrkdwn","text":scen or "_(no text)_" }},
        {"type":"context","elements":[{"type":"mrkdwn","text":f"*Score:* {score}"}]},
        {"type":"actions","elements":[
            {"type":"button","text":{"type":"plain_text","text":c},
             "value":c,"action_id":f"choice_{i}"} for i,c in enumerate(choices)
        ]}
    ]
    return blocks

# ─── 4. /cyberquest (slash) ───────────────────────────────────
@app.route("/cyberquest", methods=["POST"])
def slash():
    cmd=request.form.get("text","").strip().lower()
    uid=request.form["user_id"]

    if cmd in {"","menu","start"}:
        menu={"type":"actions","elements":[
            {"type":"button","text":{"type":"plain_text","text":"Start Training"},
             "value":"start","action_id":"start"},
            {"type":"button","text":{"type":"plain_text","text":"How to Play"},
             "value":"help","action_id":"help"},
            {"type":"button","text":{"type":"plain_text","text":"Exit"},
             "value":"exit","action_id":"exit"}
        ]}
        return jsonify({"response_type":"ephemeral",
                        "blocks":[{"type":"section",
                        "text":{"type":"mrkdwn","text":"*CyberQuest* — choose:"}},menu]})

    raw=gemini_reply(cmd,uid)
    blocks=build_blocks(raw, chat_sessions.get(uid,{}).get("score",0))
    return jsonify({"response_type":"ephemeral","blocks":blocks})

# ─── 5. interactive buttons ───────────────────────────────────
@app.route("/slack/interactive", methods=["POST"])
def interactive():
    data=json.loads(request.form["payload"])
    uid=data["user"]["id"]
    choice=data["actions"][0]["value"]

    get_chat_session(uid)         # make sure chat exists

    if choice=="start":
        chat_sessions[uid]["score"]=0
        raw=gemini_reply("start training",uid)
    elif choice=="help":
        raw=("Each scenario is *private*. Click a button to act. "
             "Good choices raise your score.")
    elif choice=="exit":
        raw="Exited CyberQuest. Use `/cyberquest start` to return."
    else:
        raw=gemini_reply(choice,uid)
        if "report" in choice.lower(): chat_sessions[uid]["score"]+=1
        elif any(k in choice.lower() for k in ("click","open")): chat_sessions[uid]["score"]-=1

    blocks=build_blocks(raw, chat_sessions[uid]["score"])

    # IMPORTANT: quick-reply that REPLACES the original message
    return jsonify({
        "replace_original": True,
        "blocks": blocks
    })

# ─── 6. local dev run ──────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
