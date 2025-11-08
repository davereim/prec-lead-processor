import os
from flask import Flask, request, jsonify
from datetime import datetime
import openai

# Plain ASCII only. No curly quotes or special punctuation.

app = Flask(__name__)

# Read API key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")

# Optional shared secret for basic auth
SHARED_SECRET = os.getenv("SHARED_SECRET", "")

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/", methods=["POST"])
def process_lead():
    # Simple auth
    if SHARED_SECRET and request.headers.get("X-Auth-Token") != SHARED_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    email_text = data.get("body", "")

    prompt = (
        "You are Dave Clone. Extract the following from this email:\n"
        "- Name\n"
        "- Email\n"
        "- Phone\n"
        "- Message summary\n"
        "- Lead type (Buyer, Seller, Foreclosure, VIPMA, Home Evaluation, Other)\n"
        "- Priority (High, Medium, Low)\n"
        "Then write a short professional reply in Dave's tone.\n\n"
        "Email content:\n"
        f"{email_text}\n"
    )

    # Call OpenAI Chat API
    resp = openai.ChatCompletion.create(
        model="gpt-5",
        messages=[
            {
                "role": "system",
                "content": "You are Dave Clone, a professional Greater Vancouver realtor assistant. No emojis. No marketing fluff."
            },
            {"role": "user", "content": prompt},
        ],
    )

    result_text = resp.choices[0].message["content"]

    log = {
        "timestamp": datetime.utcnow().isoformat(),
        "email_text": email_text,
        "result": result_text,
    }
    print("Processed lead:", log)
    return jsonify(log), 200

if __name__ == "__main__":
    # Render provides PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
