from flask import Flask, request, jsonify
import os
import requests
import threading

app = Flask(__name__)

# 🔑 Gemini API call
def call_gemini_api(user_input, user_id):
    prompt = f"""
You are the narrator of a Slack-based cybersecurity adventure game called *CyberQuest*. 
Continue the immersive story based on the user’s command.

User ID: {user_id}
Command: "{user_input}"
"""

    # Note: Remove the Authorization header and pass the API key as a query parameter.
    headers = {
        "Content-Type": "application/json"
    }

    body = {
        "prompt": {
            "messages": [
                {"author": "user", "content": prompt}
            ]
        },
        "temperature": 0.9,
        "candidateCount": 1
    }

    # Append the API key as a query parameter instead of sending it as a Bearer token.
    api_key = os.getenv('GEMINI_API_KEY')
    url = f"https://generativelanguage.googleapis.com/v1beta2/models/chat-bison-001:generateMessage?key={api_key}"

    try:
        response = requests.post(url, headers=headers, json=body)
        result = response.json()
        print("🔍 Gemini raw response:", result)

        if 'candidates' in result and result['candidates']:
            return result['candidates'][0]['content']
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
