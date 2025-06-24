# cyberquestadv.py

adventure_sessions = {}  # user_id → current scene, tags, score, inventory, etc.

# Sample scene structure (normally loaded from JSON later)
SCENES = {
    "intro": {
        "description": (
            "*🌐 Scene: Suspicious Login*\n"
            "Your terminal flashes: `Login attempt from Kyiv, Ukraine.`\n\n"
            "There’s a half-drunk coffee on your desk. You didn’t touch it.\n\n"
            "*What do you do?*"
        ),
        "choices": [
            {"text": "Ignore it", "next_scene": "phishing_trap"},
            {"text": "Report to IT", "next_scene": "safe_path"}
        ]
    },
    "phishing_trap": {
        "description": "The next morning, your credentials are leaked. HR calls you in.\n\n*Game Over.*",
        "choices": []
    },
    "safe_path": {
        "description": "IT confirms it was a phishing attempt. You narrowly avoided a breach. You live to work another day.",
        "choices": []
    }
}

def handle_adventure_start(user_id):
    # Start a session
    adventure_sessions[user_id] = {
        "current_scene": "intro",
        "tags": [],
        "score": 0,
    }
    return build_scene_blocks(user_id)

def build_scene_blocks(user_id):
    session = adventure_sessions.get(user_id)
    scene = SCENES[session["current_scene"]]

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": scene["description"]}
        }
    ]

    if scene["choices"]:
        buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": choice["text"]},
                "action_id": f"adv_{i}",
                "value": f"{user_id}:{i}"
            } for i, choice in enumerate(scene["choices"])
        ]
        blocks.append({"type": "actions", "elements": buttons})

    return blocks

def handle_adventure_choice(action_id, value):
    user_id, choice_idx = value.split(":")
    session = adventure_sessions.get(user_id)
    scene = SCENES[session["current_scene"]]
    choice = scene["choices"][int(choice_idx)]

    # Move to next scene
    session["current_scene"] = choice["next_scene"]
    return build_scene_blocks(user_id)
