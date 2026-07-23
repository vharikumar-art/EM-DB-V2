"""
Pure Python Personalizer
========================
Replaces [name], [company], [industry], etc. with lead data.
Does not use LangChain or AI.
"""

PLACEHOLDER_MAP = {
    "name":        lambda lead: _get_first_name(lead.get("fullName", "")),
    "full_name":   lambda lead: lead.get("fullName", ""),
    "company":     lambda lead: lead.get("company", ""),
    "industry":    lambda lead: lead.get("industry", ""),
    "designation": lambda lead: lead.get("designation", ""),
    "country":     lambda lead: lead.get("country", ""),
    "domain":      lambda lead: lead.get("domain", ""),
    "city":        lambda lead: lead.get("city", ""),
    "state":       lambda lead: lead.get("state", ""),
    "website":     lambda lead: lead.get("website", ""),
    "linkedin":    lambda lead: lead.get("linkedin", ""),
    "phone":       lambda lead: lead.get("phone", ""),
    "email":       lambda lead: lead.get("email", ""),
}

def _get_first_name(full_name: str) -> str:
    """Extract first name."""
    if not full_name or not full_name.strip():
        return "there"
    parts = full_name.strip().split()
    return parts[0].capitalize()


def personalize(
    subject: str,
    body: str,
    signature: str,
    lead: dict,
) -> tuple[str, str]:
    """Replace placeholders in subject and body."""
    final_subject = subject
    final_body = body
    
    for key, resolver in PLACEHOLDER_MAP.items():
        value = (resolver(lead) or "").strip()
        placeholder = f"[{key}]"
        
        if placeholder in final_subject:
            final_subject = final_subject.replace(placeholder, value)
            
        if placeholder in final_body:
            final_body = final_body.replace(placeholder, value)

    # Append signature
    if signature and signature.strip():
        final_body = final_body.rstrip() + "\n\n" + signature.strip()

    return final_subject, final_body


def build_email_payload(
    profile: dict,
    lead: dict,
    template: dict | None = None,
) -> dict:
    """
    Constructs the final personalized email text.
    Uses a provided template, or falls back to profile default template.
    """
    # 1. Base content (Template > Profile default)
    if template:
        raw_subject = template.get("subject", "")
        raw_body = template.get("body", "")
    else:
        raw_subject = profile.get("subject", "")
        raw_body = profile.get("promptSettings", {}).get("customInstruction", "")

    sig = profile.get("signature", "")

    # 2. Pure string replacement
    subj_text, body_text = personalize(raw_subject, raw_body, sig, lead)

    return {
        "to": lead.get("email", ""),
        "subject": subj_text,
        "body": body_text,
        "html": body_text.replace("\n", "<br>"),  # naive text-to-HTML
    }
