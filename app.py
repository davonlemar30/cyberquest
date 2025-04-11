from flask import Flask, request, jsonify
import os
import requests
import threading
import base64
import json
import google.generativeai as genai
from google.oauth2 import service_account

app = Flask(__name__)
chat_sessions = {}

# 🔐 Load credentials from base64 JSON (Render ENV)
def get_google_credentials():
    encoded = os.getenv("GEMINI_SERVICE_ACCOUNT")
    if not encoded:
        raise Exception("Missing GEMINI_SERVICE_ACCOUNT in environment")
    service_account_info = json.loads(base64.b64decode(encoded).decode("utf-8"))
    return service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/generative-language"]
    )

# 🔁 Initialize Gemini client once
credentials = get_google_credentials()
genai.configure(credentials=credentials)

# 💬 Manage conversation sessions
def get_chat_session(conversation_id):
    if conversation_id not in chat_sessions:
        session = genai.GenerativeModel("models/gemini-1.5-flash").start_chat(
            history=[
                {"role": "user", "parts": ["You are the narrator of a Slack-based cybersecurity text adventure game called *CyberQuest*. Guide the user through immersive, engaging, and educational cybersecurity scenarios based on their commands. Continue the story until they type 'exit'."]}
            ]
        )
        chat_sessions[conversation_id] = session
    return chat_sessions[conversation_id]

# 🧠 Main Gemini interaction
def call_gemini_flash(user_input, conversation_id):
    try:
        session = get_chat_session(conversation_id)
        response = session.send_message(user_input)
        return response.text
    except Exception as e:
        return f"⚠️ Gemini Error: {e}"

# 🧵 Background thread handler for Slack
def handle_gemini_response(response_url, user_input, user_id):
    reply = call_gemini_flash(user_input, user_id)
    requests.post(response_url, json={
        "response_type": "in_channel",
        "text": reply
    })

# 🚪 Slack endpoint
@app.route("/cyberquest", methods=["POST"])
def cyberquest():
    user_input = request.form.get("text")
    user_id = request.form.get("user_id")
    response_url = request.form.get("response_url")

    threading.Thread(target=handle_gemini_response, args=(response_url, user_input, user_id)).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "🧠 Processing your CyberQuest move..."
    })

if __name__ == "__main__":
    app.run(debug=True)
