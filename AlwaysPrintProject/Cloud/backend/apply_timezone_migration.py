"""
Script para aplicar la migración de timezone manualmente.
"""
from app.core.database import engine
import sqlalchemy as sa

with engine.connect() as conn:
    try:
        # Agregar timezone a accounts
        conn.execute(sa.text('ALTER TABLE accounts ADD COLUMN timezone VARCHAR(50) NOT NULL DEFAULT "UTC"'))
        print("✓ Campo timezone agregado a accounts")
    except Exception as e:
        print(f"Campo timezone en accounts ya existe o error: {e}")
    
    try:
        # Agregar timezone a users
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN timezone VARCHAR(50)'))
        print("✓ Campo timezone agregado a users")
    except Exception as e:
        print(f"Campo timezone en users ya existe o error: {e}")
    
    conn.commit()
    print("\n✅ Migración completada")
