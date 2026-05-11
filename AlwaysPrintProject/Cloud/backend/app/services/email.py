import logging
import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    if not settings.SES_ENABLED:
        logger.info("SES deshabilitado — reset URL: %s", reset_url)
        return True

    subject = "Restablecer contraseña — AlwaysPrint Cloud Manager"
    body_text = (
        f"Haz clic en el siguiente enlace para restablecer tu contraseña:\n\n"
        f"{reset_url}\n\n"
        f"Este enlace expira en 1 hora.\n\n"
        f"Si no solicitaste este cambio, ignora este mensaje."
    )
    body_html = f"""
    <html><body style="font-family:sans-serif;max-width:480px;margin:40px auto">
      <h2 style="color:#1d4ed8">AlwaysPrint Cloud Manager</h2>
      <p>Haz clic en el siguiente enlace para restablecer tu contraseña:</p>
      <p style="margin:24px 0">
        <a href="{reset_url}" style="background:#1d4ed8;color:#fff;padding:12px 24px;
           border-radius:6px;text-decoration:none;font-weight:bold">
          Restablecer contraseña
        </a>
      </p>
      <p style="color:#6b7280;font-size:14px">
        Este enlace expira en 1 hora.<br>
        Si no solicitaste este cambio, ignora este mensaje.
      </p>
    </body></html>
    """

    try:
        client = boto3.client("ses", region_name=settings.AWS_REGION)
        client.send_email(
            Source=settings.SES_FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        logger.info("Email de reset enviado a %s", to_email)
        return True
    except ClientError as e:
        logger.error("SES error enviando a %s: %s", to_email, e.response["Error"]["Message"])
        return False
