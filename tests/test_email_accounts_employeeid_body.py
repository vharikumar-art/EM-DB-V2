from app.email_accounts.schema import EmailAccountCreate


def test_email_account_create_accepts_employee_id_in_body():
    payload = EmailAccountCreate(
        email="admin@example.com",
        appPassword="secret",
        employeeId="emp_123",
    )

    assert payload.employeeId == "emp_123"
