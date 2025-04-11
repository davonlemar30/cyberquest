from flask import Flask, request, jsonify
import os
import requests
import threading

app = Flask(__name__)

# 🔑 Gemini API call
def call_gemini_api(user_input, user_id):
    api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        return "⚠️ ERROR: GEMINI_API_KEY is not being loaded from the environment."

    prompt = f"""
You are the narrator of an interactive cybersecurity adventure called *CyberQuest*. 
User ID: {user_id}
User Command: "{user_input}"
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    body = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
            headers=headers,
            json=body
        )
        result = response.json()

        if 'candidates' in result and result['candidates']:
            return result['candidates'][0]['content']['parts'][0]['text']
        elif 'error' in result:
            return f"⚠️ Gemini API Error: {result['error'].get('message', 'Unknown error')}"
        else:
            return f"⚠️ Unexpected response from Gemini:\n{result}"
    except Exception as e:
        return f"⚠️ Exception calling Gemini: {e}"




# 🧵 Gemini logic in a background thread
def handle_gemini_response(response_url, user_input, user_id):
    gemini_reply = call_gemini_api(user_input, user_id)
    requests.post(response_url, json={
        "response_type": "in_channel",  # Or "ephemeral" for private replies
        "text": gemini_reply
    })

# 🚪 Slack endpoint
@app.route("/cyberquest", methods=["POST"])
def cyberquest():
    user_input = request.form.get("text")
    user_id = request.form.get("user_id")
    response_url = request.form.get("response_url")

    # Immediately respond to Slack to prevent timeout
    threading.Thread(target=handle_gemini_response, args=(response_url, user_input, user_id)).start()

    return jsonify({
        "response_type": "ephemeral",
        "text": "🧠 Processing your CyberQuest move..."
    })

if __name__ == "__main__":
    app.run(debug=True)
