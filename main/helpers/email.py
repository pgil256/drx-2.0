import smtplib
from email.mime.text import MIMEText


def email_admin(username, user_email, user_status):
    sender_email = "ksdrxsmpt@gmail.com"
    sender_password = "Abbygal01"
    receiver_email = "ksdrxsmpt@gmail.com"  # Could be the same as sender

    subject = "Assistance Request"
    body = f"User ({username}) with email ({user_email}) and status ({user_status}) is requesting assistance."
    print(body)

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        print("Assistance request email sent successfully.")
    except Exception as e:
        print(f"Failed to send assistance email: {e}")
