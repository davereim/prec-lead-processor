from flask import Flask, request, jsonify
import openai
import os
from datetime import datetime

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/", methods=["POST"])
def process_lead():
    data = request.json
    email_text = data.get("body", "")

    prompt = f"""
    You are Dave Clone. Extract the following from this email:
    - Name
    - Email
    - Phone
    - Message summary
    - Lead type (Buyer, Seller, Foreclosure, VIPMA, Home Evaluation, Other)
    - Priority (High, Medium, Low)
    Then write a short professional reply in Dave’s tone.

    Email content:
    {email_text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-5",
        messages=[{"role": "system", "content": "You are Dave Clone, a professional realtor assistant."},
                  {"role": "user", "content": prompt}]
    )

    result = response.choices[0].message["content"]

    log = {
        "timestamp": datetime.utcnow().isoformat(),
        "email_text": email_text,
        "result": result
    }

    print("Processed lead:", log)
    return jsonify(log)
