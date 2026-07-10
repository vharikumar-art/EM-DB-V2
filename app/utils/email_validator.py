from email_validator import EmailNotValidError, validate_email


def is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    try:
        validate_email(email.strip(), check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()
