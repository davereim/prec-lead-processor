import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# OpenAI client (new SDK)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Optional: simple shared secret so only your script can call this
INCOMING_API_KEY = os.getenv("INCOMING_API_KEY", "")

SYSTEM_PROMPT = (
    "You are Dave Clone, assistant to a Greater Vancouver realtor. "
    "Write short, professional replies in Dave's voice. No emojis. "
    "No flowery marketing language. Be clear and calm."
)

# Ask the model to return strict JSON we can parse
JSON_INSTRUCTIONS = """
Return ONLY valid JSON with this exact structure:
{
  "name": string | null,
  "email": string | null,
  "phone": string | null,
  "lead_type": "Buyer" | "Seller" | "Foreclosure" | "VIPMA" | "Home Evaluation" | "Other",
  "priority": "High" | "Medium" | "Low",
  "summary": string,
  "reply": string
}
Do not include any extra keys or prose. Only JSON.
"""

@app.route("/", methods=["POST"])
def process_lead():
    # Optional auth
    if INCOMING_API_KEY and request.headers.get("X-API-Key") != INCOMING_API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    email_text = data.get("body", "").strip()

    if not email_text:
        return jsonify({"error": "missing 'body' in JSON"}), 400

    user_prompt = f"""
Extract lead details from this email and write a reply in Dave's style.

{JSON_INSTRUCTIONS}

Email content:
\"\"\"
{email_text}
\"\"\"
"""

    # NEW API CALL SIGNATURE
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",  # you can change to another model that's available to your key
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content
    except Exception as e:
        return jsonify({"error": f"openai_error: {str(e)}"}), 500

    # Try to parse JSON. If it fails, fall back to a basic reply-only payload.
    parsed = None
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {
            "name": None,
            "email": None,
            "phone": None,
            "lead_type": "Other",
            "priority": "Medium",
            "summary": email_text[:500],
            "reply": content
        }

    out = {
        "timestamp": datetime.utcnow().isoformat(),
        "input_preview": email_text[:500],
        "result": parsed
    }
    print("Processed lead:", out)  # shows in Render logs
    return jsonify(out), 200


# Render/Flask entrypoint
if __name__ == "__main__":
    # Render provides PORT env var
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
