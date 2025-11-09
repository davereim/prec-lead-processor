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

# Global "Dave" system prompt
BASE_SYSTEM_PROMPT = (
    "You are Daver AI Clone, a digital assistant for David Reimers, "
    "a Greater Vancouver residential realtor focused on Coquitlam. "
    "Write short, professional replies in Dave's voice. No emojis. "
    "No flowery marketing language. Be clear, calm, and helpful. "
    "Use plain ASCII punctuation (no curly quotes, no smart quotes, no ellipsis character)."
)

# Instructions for the lead-extraction style task
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
The reply should NOT include David's full email signature block. End with a natural closing like "Cheers, David".
Do not include any extra keys or prose. Only JSON.
"""


def call_openai(messages, model="gpt-4o", temperature=0.2):
    """Small helper so we only write the OpenAI call once."""
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content


def normalize_punctuation(text: str) -> str:
    """
    Convert common smart punctuation to plain ASCII.
    We do NOT strip all non-ASCII (to avoid breaking names), just the usual suspects.
    """
    if not isinstance(text, str):
        return text

    replacements = {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
        "\u00a0": " ",  # non-breaking space
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def handle_gmail_lead_reply(email_text: str) -> dict:
    """
    Extract lead details and write a reply in Dave's style.
    Returns a dict matching JSON_INSTRUCTIONS.
    """
    user_prompt = f"""
Extract lead details from this email and write a reply in Dave's style.

{JSON_INSTRUCTIONS}

Email content:
\"\"\" 
{email_text}
\"\"\" 
"""

    try:
        content = call_openai(
            messages=[
                {"role": "system", "content": BASE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
    except Exception as e:
        # If OpenAI call fails, we still return a minimal structure
        fallback_reply = (
            "Hi there,\n\n"
            "Thanks for reaching out. I saw your note and will follow up shortly.\n\n"
            "Cheers,\n"
            "David"
        )
        return {
            "name": None,
            "email": None,
            "phone": None,
            "lead_type": "Other",
            "priority": "Medium",
            "summary": email_text[:500],
            "reply": fallback_reply,
            "error": f"openai_error: {str(e)}",
        }

    # Try to parse JSON. If it fails, fall back to a basic reply-only payload.
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
            "reply": content,
        }

    # Ensure all expected keys exist
    for key, default in [
        ("name", None),
        ("email", None),
        ("phone", None),
        ("lead_type", "Other"),
        ("priority", "Medium"),
        ("summary", email_text[:500]),
        ("reply", ""),
    ]:
        if key not in parsed:
            parsed[key] = default

    # Normalize punctuation on text fields
    for k in ["name", "email", "phone", "summary", "reply"]:
        if parsed.get(k):
            parsed[k] = normalize_punctuation(parsed[k])

    return parsed


def build_reply_html_from_result(result: dict) -> str:
    """
    Take the GPT result dict and build final HTML reply, with:
    - normalized ASCII punctuation
    - default HTML signature appended
    """
    reply_text = normalize_punctuation(result.get("reply") or "")

    if reply_text:
        # Split into paragraphs on double newlines
        parts = [p.strip() for p in reply_text.split("\n\n") if p.strip()]
        if len(parts) > 1:
            body_html = "<p>" + "</p><p>".join(
                p.replace("\n", "<br>") for p in parts
            ) + "</p>"
        else:
            body_html = "<p>" + reply_text.replace("\n", "<br>") + "</p>"
    else:
        body_html = "<p>Hi there,</p><p>Thanks for your message. I will review it and follow up with next steps.</p>"

    # Default HTML signature (ASCII-friendly)
    signature_html = """
<p>Cheers,<br>
David Reimers PREC*<br>
Royal LePage West Real Estate Services<br>
604-340-9822<br>
<a href="https://reimers.ca">reimers.ca</a></p>
""".strip()

    full_html = f"{body_html}\n{signature_html}"
    return full_html


@app.route("/lead", methods=["POST"])
def lead_endpoint():
    """
    Endpoint used by the Gmail Apps Script.

    - Accepts payload with body/body_text, from_name, from_email, subject, etc.
    - Uses the Daver AI Clone GPT logic (handle_gmail_lead_reply) to generate a reply.
    - Returns JSON containing parsed lead info + reply_html (with default signature).
    """
    # Optional auth
    if INCOMING_API_KEY and request.headers.get("X-API-Key") != INCOMING_API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    # Accept either "body" or "body_text" from Apps Script
    body = data.get("body") or data.get("body_text") or ""
    body = (body or "").strip()

    if not body:
        return jsonify({"error": "missing 'body' or 'body_text' in JSON"}), 400

    from_name = data.get("from_name") or "there"
    from_email = data.get("from_email")
    subject = data.get("subject") or ""
    phone = data.get("phone")
    source = data.get("source") or "gmail"

    # Use your Daver AI Clone GPT JSON template
    result = handle_gmail_lead_reply(body)

    # Prefer explicit metadata if GPT left these blank
    result_name = result.get("name") or from_name
    result_email = result.get("email") or None  # let Apps Script choose fallback
    result_phone = result.get("phone") or phone

    reply_html = build_reply_html_from_result(result)

    result["name"] = result_name
    result["email"] = result_email
    result["phone"] = result_phone
    result["reply_html"] = reply_html
    result["source"] = source

    print("Lead endpoint processed:", json.dumps(result, ensure_ascii=False)[:800])
    return jsonify(result), 200


@app.route("/", methods=["POST"])
def process_lead_or_task():
    """
    Backwards-compatible root endpoint (still available if you ever use it).
    """
    if INCOMING_API_KEY and request.headers.get("X-API-Key") != INCOMING_API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    body = data.get("body") or data.get("body_text") or ""
    body = (body or "").strip()

    if not body:
        return jsonify({"error": "missing 'body' or 'body_text' in JSON"}), 400

    result = handle_gmail_lead_reply(body)

    out = {
        "timestamp": datetime.utcnow().isoformat(),
        "task_type": "gmail_lead_reply",
        "input_preview": body[:500],
        "meta": {
            "from_name": data.get("from_name"),
            "from_email": data.get("from_email"),
            "subject": data.get("subject"),
            "phone": data.get("phone"),
            "source": data.get("source"),
        },
        "result": result,
    }

    print("Processed /:", json.dumps(out, ensure_ascii=False)[:1000])
    return jsonify(out), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()}), 200


# Render/Flask entrypoint
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
