from google.oauth2 import service_account
from googleapiclient.discovery import build
import base64
from email.message import EmailMessage
from email.utils import formataddr

def send_ticket_email(user_email, user_name, issue_text):
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    # Load credentials from service_account.json and impersonate the user
    creds = service_account.Credentials.from_service_account_file(
        "service_account.json",
        scopes=SCOPES
    ).with_subject(user_email)
    
    service = build("gmail", "v1", credentials=creds)
    
    message = EmailMessage()
    message.set_content(f"Issue reported by {user_name} ({user_email}):\n\n{issue_text}")
    # Include display names in headers
    message["From"] = formataddr((user_name, user_email))
    message["To"] = formataddr(("IT Ticket", "rt@microcom.tv"))
    snippet = issue_text[:50] if issue_text else "Slack IT Request"
    message["Subject"] = f"Ticket: {snippet}"
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    send_body = {"raw": raw}
    
    service.users().messages().send(userId="me", body=send_body).execute()
    print(f"✅ Support email sent successfully from {user_email}")
