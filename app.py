from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

@app.route("/cyberquest", methods=["POST"])
def cyberquest():
    user_input = request.form.get("text")
    user_id = request.form.get("user_id")

    # Gemini API call
    gemini_response = call_gemini_api(user_input, user_id)

    return jsonify({
        "response_type": "in_channel",
        "text": gemini_response
    })

def call_gemini_api(user_input, user_id):
    # Setup prompt and system state
    prompt = f"""You are a cyber security trainer in the form of a text adventure game.
User ID: {user_id}
Current Input: "{user_input}"

Respond with the next scene or outcome based on what the user typed."""
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('GEMINI_API_KEY')}"
    }

    body = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
        headers=headers,
        json=body
    )

    result = response.json()
    try:
        return result['candidates'][0]['content']['parts'][0]['text']
    except:
        return "Sorry, something went wrong with the AI response."

if __name__ == "__main__":
    app.run(debug=True)
