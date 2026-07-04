"""
One-shot script: Backfill ecdsa_cert_hash para organizaciones existentes.

Lee el certificado (.cer) desde S3 para cada org que tiene cert configurado,
computa SHA256, y actualiza la columna ecdsa_cert_hash en la BD.

Uso:
    cd AlwaysPrintProject/Cloud/backend
    python scripts/backfill_cert_hash.py

Requiere:
    - Variables de entorno: DATABASE_URL, AWS_PROFILE o credenciales S3
    - Acceso a S3 bucket de configuraciones
"""

import hashlib
import sys
import os

# Agregar app al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.services.s3_config_service import S3ConfigService


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL no definida")
        sys.exit(1)

    engine = create_engine(database_url)
    s3_service = S3ConfigService()

    with engine.connect() as conn:
        # Buscar orgs con cert configurado pero sin hash
        rows = conn.execute(text("""
            SELECT id, ecdsa_cert_s3_key, ecdsa_cert_version
            FROM organizations
            WHERE ecdsa_cert_s3_key IS NOT NULL
              AND ecdsa_cert_version > 0
              AND (ecdsa_cert_hash IS NULL OR ecdsa_cert_hash = '')
        """)).fetchall()

        print(f"Organizaciones por actualizar: {len(rows)}")

        updated = 0
        for row in rows:
            org_id = str(row.id)
            s3_key = row.ecdsa_cert_s3_key
            cert_version = row.ecdsa_cert_version

            try:
                # Descargar cert desde S3
                cert_content = s3_service.download_file_content(s3_key)
                if not cert_content:
                    print(f"  [{org_id}] ERROR: no se pudo descargar {s3_key}")
                    continue

                # Computar SHA256
                if isinstance(cert_content, str):
                    cert_bytes = cert_content.encode("utf-8")
                else:
                    cert_bytes = cert_content

                cert_hash = hashlib.sha256(cert_bytes).hexdigest()

                # Actualizar en BD
                conn.execute(text("""
                    UPDATE organizations
                    SET ecdsa_cert_hash = :cert_hash
                    WHERE id = :org_id
                """), {"cert_hash": cert_hash, "org_id": org_id})

                updated += 1
                print(f"  [{org_id}] OK: cert_version={cert_version}, hash={cert_hash[:16]}...")

            except Exception as e:
                print(f"  [{org_id}] ERROR: {e}")

        conn.commit()
        print(f"\nCompletado: {updated}/{len(rows)} organizaciones actualizadas.")


if __name__ == "__main__":
    main()
