# cyberquestadv.py

# In-memory store: user_id → session data
adventure_sessions = {}

# Scene definitions, with {player_name} placeholder
SCENES = {
    "choose_role": {
        "description": (
            "*👋 Hello {player_name}, welcome to CyberQuest!*\n\n"
            "Choose your role in the company — each department faces unique threats:\n"
            "• *Sales* (Phishing, spoofed clients)\n"
            "• *Dispatch* (Fake tickets, urgent scams)\n"
            "• *Technician* (USB drops, rogue Wi-Fi)\n"
            "• *IT (Hard Mode)* (Ransomware, privilege escalation)\n"
            "• *CEO* (Spear phishing, blackmail)\n\n"
            "*Which will you be?*"
        ),
        "choices": [
            {"text": "Sales",       "next_scene": "sales_intro",    "tags_added": ["role_sales"]},
            {"text": "Dispatch",    "next_scene": "dispatch_intro", "tags_added": ["role_dispatch"]},
            {"text": "Technician",  "next_scene": "tech_intro",     "tags_added": ["role_technician"]},
            {"text": "IT (Hard)",   "next_scene": "it_intro",       "tags_added": ["role_it"]},
            {"text": "CEO",         "next_scene": "ceo_intro",      "tags_added": ["role_ceo"]}
        ]
    },

        # ── Sales: Step 1 — Create Your Password ─────────────────────────
    "sales_intro": {
        "description": (
            "*📥 Welcome to Microcom Sales!* 🚀\n"
            "It’s your first day—HR hands you your onboarding package and your new Gmail login. "
            "When you log in, you’re immediately prompted to *create* a password.\n\n"
            "*Choose the strongest realistic password:*"
        ),
        "choices": [
            {
                "text": "Password123!",
                "next_scene": "sales_email",
                "tags_added": ["weak_password"],
                "score_change": -2
            },
            {
                "text": "Spring2025*Sale",
                "next_scene": "sales_email",
                "tags_added": ["ok_password"],
                "score_change": 0
            },
            {
                "text": "M!cr0c0m$4l3s*",
                "next_scene": "sales_email",
                "tags_added": ["strong_password"],
                "score_change": 2
            },
            {
                "text": "1234567890",
                "next_scene": "sales_email",
                "tags_added": ["terrible_password"],
                "score_change": -3
            }
        ]
    },

    # ── Sales: Step 2 — First Sales Email ─────────────────────────────
    "sales_email": {
        "description": (
            "*📞 Sales Intro Continued*\n\n"
            "Now that you’ve set your password, you open Gmail and see:\n\n"
            "> From: client@example.com\n"
            "> Subject: ‘Request for quote’\n\n"
            "The domain looks off—what do you do?"
        ),
        "choices": [
            {
                "text": "Reply with pricing info",
                "next_scene": "phishing_trap",
                "tags_added": ["ignored_red_flag"],
                "score_change": -1
            },
            {
                "text": "Forward to IT Security",
                "next_scene": "safe_path",
                "tags_added": ["reported_phish"],
                "score_change": 1
            }
        ]
    },


    "dispatch_intro": {
        "description": "*📦 Dispatch Intro*\n\nA new ticket pops up: “URGENT: Customer’s router is offline—reset now!” The request came via an unknown third-party email.\n\n*How do you proceed?*",
        "choices": [
            {"text": "Reset the router immediately",         "next_scene": "fake_reset_interface", "tags_added": ["rushed_without_verify"]},
            {"text": "Verify ticket origin with the client", "next_scene": "safe_path"}
        ]
    },

    "tech_intro": {
        "description": "*🛠️ Technician Intro*\n\nYou arrive onsite; a USB drive lies on the receptionist’s desk labeled “HR Payroll Update.”\n\n*Do you:*",
        "choices": [
            {"text": "Plug it into your laptop to inspect", "next_scene": "malware_injection", "tags_added": ["unsafe_usb_use"]},
            {"text": "Turn it over to IT security",         "next_scene": "safe_path"}
        ]
    },

    "it_intro": {
        "description": "*🔐 IT Admin Intro*\n\nYour monitoring dashboard flags a spike in outbound traffic to an unfamiliar IP.\n\n*Your first step?*",
        "choices": [
            {"text": "Run a full network scan",           "next_scene": "network_scan_results", "tags_added": ["proactive_it"]},
            {"text": "Ignore—it’s probably a false alarm", "next_scene": "data_exfiltration", "tags_added": ["dismissed_alert"] }
        ]
    },

    "ceo_intro": {
        "description": "*🏢 CEO Intro*\n\nYou receive a personalized voicemail: “We have sensitive documents on you—\$10,000 to keep them private.” The caller knows your home address.\n\n*Your move?*",
        "choices": [
            {"text": "Pay the ransom immediately",     "next_scene": "financial_loss", "tags_added": ["succumbed_to_blackmail"]},
            {"text": "Contact legal & security team", "next_scene": "borough_secure",  "tags_added": ["escalated_to_experts"] }
        ]
    },

    # existing follow-up scenes like 'phishing_trap', 'safe_path', etc.
    "phishing_trap": {
        "description": "_A day later, your inbox fills with ransomware demands. Game Over._",
        "choices": []
    },
    "safe_path": {
        "description": "_Well done! You avoided the trap and secured your assets. You live to work another day._",
        "choices": []
    },
    "fake_reset_interface": {
        "description": "_The “reset” portal you opened was a spoof. Credentials harvested!_",
        "choices": []
    },
    "malware_injection": {
        "description": "_That USB installed a keylogger. Credentials stolen!_",
        "choices": []
    },
    "network_scan_results": {
        "description": "_Scan shows malware beaconing. You block the IP and isolate the machine. Crisis averted!_",
        "choices": []
    },
    "data_exfiltration": {
        "description": "_Massive data exfiltration completes overnight. Security breach!_",
        "choices": []
    },
    "financial_loss": {
        "description": "_You wired the money—now you’re out ten grand and still compromised._",
        "choices": []
    },
    "borough_secure": {
        "description": "_Your security team neutralized the threat; no data leaked. Well played!_",
        "choices": []
    }
}

def handle_adventure_start(user_id: str, player_name: str):
    """Initialize a new adventure session."""
    adventure_sessions[user_id] = {
        "current_scene": "choose_role",
        "tags": [],
        "score": 0,
        "player_name": player_name
    }
    return build_scene_blocks(user_id)

def build_scene_blocks(user_id: str):
    """Build Slack Block Kit for the current scene."""
    session = adventure_sessions[user_id]
    scene = SCENES[session["current_scene"]]

    # Inject player_name into description
    desc = scene["description"].format(player_name=session["player_name"])

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": desc}}
    ]

    if scene["choices"]:
        buttons = []
        for idx, choice in enumerate(scene["choices"]):
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": choice["text"]},
                "action_id": f"adv_{idx}",
                "value": f"{user_id}:{idx}"
            })
        blocks.append({"type": "actions", "elements": buttons})

    return blocks

def handle_adventure_choice(action_id: str, value: str):
    """Advance the session based on which choice was clicked."""
    user_id, choice_idx = value.split(":")
    session = adventure_sessions[user_id]
    scene = SCENES[session["current_scene"]]
    choice = scene["choices"][int(choice_idx)]

    # Add any tags
    if "tags_added" in choice:
        session["tags"].extend(choice["tags_added"])

    # Advance to next scene
    session["current_scene"] = choice["next_scene"]
    return build_scene_blocks(user_id)
