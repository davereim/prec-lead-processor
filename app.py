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
    "No flowery marketing language. Be clear, calm, and helpful."
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


def handle_gmail_lead_reply(email_text: str) -> dict:
    """
    Original behavior: extract lead details and write a reply in Dave's style.
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
        return {
            "name": None,
            "email": None,
            "phone": None,
            "lead_type": "Other",
            "priority": "Medium",
            "summary": email_text[:500],
            "reply": (
                "Hi there,\n\n"
                "Thanks for reaching out. I saw your note and will follow up shortly.\n\n"
                "Cheers,\n"
                "David\n"
            ),
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

    return parsed


def handle_generic_task(task_type: str, body: str, meta: dict) -> dict:
    """
    Future-friendly generic handler for non-lead tasks.
    For now, it just writes a good reply in Dave's voice.
    You can expand this later per task_type.
    """
    # Build a bit of context from meta if available
    from_name = meta.get("from_name") or ""
    from_email = meta.get("from_email") or ""
    subject = meta.get("subject") or ""

    context_lines = []
    if from_name or from_email:
        context_lines.append(f"From: {from_name} <{from_email}>")
    if subject:
        context_lines.append(f"Subject: {subject}")
    if task_type:
        context_lines.append(f"Task type: {task_type}")

    context_block = "\n".join(context_lines)

    user_prompt = f"""
{context_block}

Here is the text to work with:
\"\"\" 
{body}
\"\"\" 

Task:
- Understand the message.
- Write a clear, short reply in David's voice.
- Keep it professional and human, not salesy.
- Ask 1–2 relevant follow up questions if helpful.

Return ONLY plain text for the reply. No JSON, no markdown, no explanation.
"""

    try:
        reply_text = call_openai(
            messages=[
                {"role": "system", "content": BASE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
    except Exception as e:
        reply_text = (
            "Hi there,\n\n"
            "Thanks for your message. I will review it and follow up with next steps.\n\n"
            "Cheers,\n"
            "David\n"
            f"(Error details: {str(e)})"
        )

    # Simple generic result structure
    return {
        "name": meta.get("from_name"),
        "email": meta.get("from_email"),
        "phone": meta.get("phone"),
        "lead_type": "Other",
        "priority": "Medium",
        "summary": body[:500],
        "reply": reply_text,
    }


@app.route("/", methods=["POST"])
def process_lead_or_task():
    """
    Main entry point for Daver Brain.

    Backwards compatible:
    - If caller only sends { "body": "..." } it behaves like the old lead processor.
    Extended:
    - If caller sends { "task_type": \"...\", \"body\": \"...\", ... } it can do other jobs.
    """
    # Optional auth
    if INCOMING_API_KEY and request.headers.get("X-API-Key") != INCOMING_API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    # Backwards compatible: original field name used by your Apps Script
    body = data.get("body") or data.get("body_text") or ""
    body = body.strip()

    if not body:
        return jsonify({"error": "missing 'body' or 'body_text' in JSON"}), 400

    task_type = data.get("task_type") or "gmail_lead_reply"

    # Optional metadata from the caller (Adapters can add these later)
    meta = {
        "from_name": data.get("from_name"),
        "from_email": data.get("from_email"),
        "subject": data.get("subject"),
        "phone": data.get("phone"),
        "source": data.get("source"),
    }

    # Route based on task_type
    if task_type == "gmail_lead_reply":
        result = handle_gmail_lead_reply(body)
    else:
        # For now, all other tasks go through a generic handler.
        result = handle_generic_task(task_type, body, meta)

    out = {
        "timestamp": datetime.utcnow().isoformat(),
        "task_type": task_type,
        "input_preview": body[:500],
        "meta": meta,
        "result": result,
    }

    print("Processed task:", json.dumps(out, ensure_ascii=False)[:1000])
    return jsonify(out), 200


@app.route("/lead", methods=["POST"])
def lead_endpoint():
    """
    Endpoint used by the Gmail Apps Script.

    - Accepts payload with body/body_text, from_name, from_email, subject, form_data, etc.
    - If it's a Harrison lead, use the fixed Harrison template.
    - Otherwise, use the Daver AI Clone GPT logic (handle_gmail_lead_reply).
    - Returns JSON containing fields + reply_html so Apps Script can create a draft.
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

    # form_data from Apps Script (parseFormBody_)
    form_data = data.get("form_data") or {}
    form_name = (form_data.get("form_name") or "").lower()
    first_name_from_form = form_data.get("first_name")

    # Detect Harrison-related leads
    lower_subject = subject.lower()
    lower_body = body.lower()
    is_harrison = (
        "harrison" in form_name
        or "harrison" in lower_subject
        or "harrison" in lower_body
    )

    if is_harrison:
        # Use your fixed Harrison template (with first name if available)
        first_name = (first_name_from_form or from_name or "there").strip()

        reply_html = f"""
<p>Hi {first_name},</p>
<p>Thanks so much for reaching out through my website and asking to stay updated on Harrison Lake properties. I’m excited to help you keep an eye on the best deals as they come up. It’s a beautiful area with a mix of cabins, waterfront homes, and unique getaway spots.</p>
<p>To make sure I send you the most relevant updates, would you be open to a quick 5-minute discovery call? That way I can learn a bit more about what you’re looking for, whether it’s a year-round home or vacation property, and tailor updates to match your goals.</p>
<p>You can reach me directly at 604-340-4400, or if you prefer, let me know a day and time that works best and I’ll give you a call.</p>
<p>Looking forward to connecting,</p>
<p>Cheers,<br>
David</p>
""".strip()

        result = {
            "name": first_name,
            "email": from_email,
            "phone": phone,
            "lead_type": "Buyer",
            "priority": "Medium",
            "summary": body[:500],
            "reply": (
                f"Hi {first_name},\n\n"
                "Thanks so much for reaching out through my website and asking to stay "
                "updated on Harrison Lake properties. I’m excited to help you keep an eye "
                "on the best deals as they come up. It’s a beautiful area with a mix of "
                "cabins, waterfront homes, and unique getaway spots.\n\n"
                "To make sure I send you the most relevant updates, would you be open to "
                "a quick 5-minute discovery call? That way I can learn a bit more about "
                "what you’re looking for, whether it’s a year-round home or vacation "
                "property, and tailor updates to match your goals.\n\n"
                "You can reach me directly at 604-340-4400, or if you prefer, let me "
                "know a day and time that works best and I’ll give you a call.\n\n"
                "Looking forward to connecting,\n\n"
                "Cheers,\n"
                "David"
            ),
            "reply_html": reply_html,
            "source": source,
        }

        print("Harrison lead endpoint processed:", json.dumps(result, ensure_ascii=False)[:800])
        return jsonify(result), 200

    # 🔹 Non-Harrison: use your Daver AI Clone GPT JSON template
    result = handle_gmail_lead_reply(body)

    # Make sure the result always has the keys we expect, and prefer caller metadata if GPT left blank
    result_name = result.get("name") or from_name
    result_email = result.get("email") or from_email
    result_phone = result.get("phone") or phone

    # Extract GPT reply text
    reply_text = result.get("reply") or ""

    # Convert reply_text (plain text with \n) to HTML
    if reply_text:
        text = reply_text.strip()
        # Split into paragraphs on double newlines
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) > 1:
            reply_html = "<p>" + "</p><p>".join(
                p.replace("\n", "<br>") for p in paragraphs
            ) + "</p>"
        else:
            reply_html = "<p>" + text.replace("\n", "<br>") + "</p>"
    else:
        # Fallback if GPT returned nothing for some reason
        reply_html = f"""
<p>Hi {from_name},</p>
<p>Thanks for your message about <b>{subject or "your inquiry"}</b>. I will review the details and follow up with next steps.</p>
<p>Cheers,<br>
David Reimers PREC*<br>
Royal LePage West Real Estate Services</p>
""".strip()

    # Attach merged fields + reply_html into result
    result["name"] = result_name
    result["email"] = result_email
    result["phone"] = result_phone
    result["reply_html"] = reply_html
    result["source"] = result.get("source") or source

    print("Non-Harrison lead endpoint processed:", json.dumps(result, ensure_ascii=False)[:800])
    return jsonify(result), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()}), 200


# Render/Flask entrypoint
if __name__ == "__main__":
    # Render provides PORT env var
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


