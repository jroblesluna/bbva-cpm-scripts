output "domain_identity_arn" {
  description = "ARN de la identidad SES"
  value       = "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:identity/${var.zone_name}"
}

output "ses_send_policy_arn" {
  description = "ARN de la política IAM de envío SES"
  value       = aws_iam_policy.ses_send.arn
}

output "from_email" {
  value = var.from_email
}

# ── Registros DNS a agregar manualmente en Hostinger (zona iol.pe) ─────────────
output "ses_dns_records" {
  description = "Registros DNS que debes agregar en Hostinger para verificar SES"
  value = {
    "1_verificacion_dominio" = {
      tipo   = "TXT"
      nombre = "_amazonses.${var.zone_name}"
      valor  = aws_ses_domain_identity.main.verification_token
    }
    "2_dkim_1" = {
      tipo   = "CNAME"
      nombre = "${aws_ses_domain_dkim.main.dkim_tokens[0]}._domainkey.${var.zone_name}"
      valor  = "${aws_ses_domain_dkim.main.dkim_tokens[0]}.dkim.amazonses.com"
    }
    "3_dkim_2" = {
      tipo   = "CNAME"
      nombre = "${aws_ses_domain_dkim.main.dkim_tokens[1]}._domainkey.${var.zone_name}"
      valor  = "${aws_ses_domain_dkim.main.dkim_tokens[1]}.dkim.amazonses.com"
    }
    "4_dkim_3" = {
      tipo   = "CNAME"
      nombre = "${aws_ses_domain_dkim.main.dkim_tokens[2]}._domainkey.${var.zone_name}"
      valor  = "${aws_ses_domain_dkim.main.dkim_tokens[2]}.dkim.amazonses.com"
    }
    "5_mail_from_mx" = {
      tipo   = "MX"
      nombre = "mail.${var.zone_name}"
      valor  = "10 feedback-smtp.${var.aws_region}.amazonses.com"
    }
    "6_mail_from_spf" = {
      tipo   = "TXT"
      nombre = "mail.${var.zone_name}"
      valor  = "v=spf1 include:amazonses.com ~all"
    }
  }
}
