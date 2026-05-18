output "instance_id" { value = aws_instance.main.id }
output "public_ip" { value = aws_eip.main.public_ip }
output "instance_profile_name" { value = aws_iam_instance_profile.ec2.name }

output "role_arn" {
  description = "ARN del rol IAM asignado al EC2"
  value       = aws_iam_role.ec2.arn
}
