# DNS gestionado en Hostinger — no hay zona Route53.
# Los registros DNS se obtienen via: terraform output ses_dns_records
# y se agregan manualmente en el panel de Hostinger (iol.pe).

resource "aws_ses_domain_identity" "main" {
  domain = var.zone_name
}

resource "aws_ses_domain_dkim" "main" {
  domain = aws_ses_domain_identity.main.domain
}

resource "aws_ses_domain_mail_from" "main" {
  domain           = aws_ses_domain_identity.main.domain
  mail_from_domain = "mail.${var.zone_name}"

  # Sin Route53 la verificación automática no aplica;
  # SES intentará verificar el dominio una vez que los TXT estén en Hostinger.
  behavior_on_mx_failure = "UseDefaultValue"
}

resource "aws_iam_policy" "ses_send" {
  name        = "${var.project_name}-${var.environment}-ses-send"
  description = "Permite enviar email via SES desde el dominio ${var.zone_name}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource = "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:identity/*"
    }]
  })
}
