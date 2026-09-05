-- =====================================================================
-- READ ONLY — Conteo de IPs (workstations) por mes de created_at, org BBVA.
-- =====================================================================
-- Task 4 (usage-and-billing): dimensionar los cierres retroactivos, es decir,
-- cuántas IPs registradas entran en el corte de cada mes (created_at < corte).
--
-- Es una consulta EXCLUSIVAMENTE de lectura (SELECT/COUNT). No escribe nada.
--
-- Ejecución recomendada en PROD vía SSM (sin SSH), dentro del contenedor del
-- backend, en una sesión de solo-lectura:
--
--   PROFILE=AlwaysPrint-prod-425642439683
--   REGION=us-west-2
--   INSTANCE=i-0b42738edf1860c00        # alwaysprint-prod-ec2 (verificar vigencia)
--
--   SQL_B64=$(base64 < scripts/bbva_ip_count_by_month.sql | tr -d '\n')
--   REMOTE="echo $SQL_B64 | base64 -d | docker exec -i alwaysprint-backend-1 \
--     sh -c 'psql \"\$DATABASE_URL\" -v ON_ERROR_STOP=1 \
--     --set=default_transaction_read_only=on -P pager=off -f -'"
--   aws ssm send-command --profile $PROFILE --region $REGION \
--     --instance-ids "$INSTANCE" --document-name "AWS-RunShellScript" \
--     --comment "READ-ONLY BBVA IP count by month" \
--     --parameters commands="[\"$REMOTE\"]"
--   # luego: aws ssm get-command-invocation --command-id <id> --instance-id $INSTANCE ...
-- =====================================================================

SELECT o.name AS org,
       date_trunc('month', w.created_at) AS mes,
       count(*) AS ips_creadas,
       min(w.created_at) AS primer_created_at,
       max(w.created_at) AS ultimo_created_at
FROM workstations w
JOIN organizations o ON o.id = w.organization_id
WHERE o.name ILIKE '%BBVA%'
GROUP BY o.name, date_trunc('month', w.created_at)
ORDER BY mes;
