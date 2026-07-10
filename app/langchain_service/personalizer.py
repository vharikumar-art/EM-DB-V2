"""
LangChain Personalizer - Placeholder Replacement Only
======================================================
Replaces [name], [company], [industry], etc. with lead data.
NO AI/LLM calls - just placeholder substitution.
"""

from langchain_core.prompts import PromptTemplate


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

_BRACKET_TO_BRACE_TABLE = str.maketrans({"[": "{", "]": "}"})


def _get_first_name(full_name: str) -> str:
    """Extract first name."""
    if not full_name or not full_name.strip():
        return "there"
    parts = full_name.strip().split()
    return parts[0].capitalize()


def _to_prompt_template_str(text: str) -> str:
    """Convert [placeholder] syntax to {placeholder} for LangChain."""
    result = text.replace("{", "{{").replace("}", "}}")
    result = result.translate(_BRACKET_TO_BRACE_TABLE)
    return result


def _build_variables(lead: dict) -> dict[str, str]:
    """Build variable dict from lead data."""
    return {
        key: (resolver(lead) or "").strip()
        for key, resolver in PLACEHOLDER_MAP.items()
    }


def _simple_replace(text: str, lead: dict) -> str:
    """Fallback: pure string replacement."""
    for key, resolver in PLACEHOLDER_MAP.items():
        value = (resolver(lead) or "").strip()
        text = text.replace(f"[{key}]", value)
    return text


def personalize(
    subject: str,
    body: str,
    signature: str,
    lead: dict,
) -> tuple[str, str]:
    """Replace placeholders - NO AI."""
    
    variables = _build_variables(lead)

    # Subject
    try:
        subject_template = PromptTemplate.from_template(
            _to_prompt_template_str(subject),
            template_format="f-string",
        )
        final_subject = subject_template.format(**variables)
    except Exception:
        final_subject = _simple_replace(subject, lead)

    # Body
    try:
        body_template = PromptTemplate.from_template(
            _to_prompt_template_str(body),
            template_format="f-string",
        )
        final_body = body_template.format(**variables)
    except Exception:
        final_body = _simple_replace(body, lead)

    # Append signature
    if signature and signature.strip():
        final_body = final_body.rstrip() + "\n\n" + signature.strip()

    return final_subject, final_body


def build_email_payload(
    profile: dict,
    lead: dict,
) -> dict:
    """Build email payload - NO AI."""
    
    subject_raw = profile.get("subject", "")
    body_raw = profile.get("body", "")
    signature = profile.get("signature", "")
    
    subject, body = personalize(subject_raw, body_raw, signature, lead)
    
    html_body = body.replace("\n", "<br>")
    
    return {
        "to": lead["email"],
        "subject": subject,
        "body": body,
        "html": html_body,
    }
