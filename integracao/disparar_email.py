import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

def enviar_email_smtp(
    smtp_username,
    smtp_password,
    region,
    sender,
    recipient,
    subject,
    body_html_path
):
    smtp_host = f"email-smtp.{region}.amazonaws.com"
    smtp_port = 587

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient

    with open(body_html_path, 'r', encoding='utf-8') as f:
        body_html = f.read()
    part2 = MIMEText(body_html, 'html', 'utf-8')
    msg.attach(part2)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(sender, recipient, msg.as_string())
        print("Email enviado via SMTP SES!")
    except Exception as e:
        print("Erro ao enviar email via SMTP SES:", str(e))

if __name__ == "__main__":
    enviar_email_smtp(
        smtp_username=os.getenv("SES_SMTP_USERNAME"),
        smtp_password=os.getenv("SES_SMTP_PASSWORD"),
        region=os.getenv("SES_SMTP_REGION"),
        sender="nao-responda2@tooseguros.com.br",
        recipient="johnnata.alves@tooseguros.com.br",
        subject="Teste SES",
        body_html_path="email.html"
    )
