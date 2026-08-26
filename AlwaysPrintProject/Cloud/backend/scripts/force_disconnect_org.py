#!/usr/bin/env python3
"""
Script para forzar la reconexión de todas las workstations de una organización.

Contexto: al restaurar un backup de BD, las workstations que seguían conectadas
NO se desconectan — su WebSocket sigue vivo en Redis bajo el WorkstationId que
tenían ANTES del restore. Si ese id ya no coincide con la fila restaurada
(típico si la workstation se re-registró aunque sea una vez desde que se tomó
el backup), el dashboard las muestra como "desconectadas" aunque en realidad
sigan funcionando.

Este script publica un mensaje al canal Redis que el backend YA escucha
(org:{organization_id}) pidiéndole que cierre esas conexiones. Cada Tray
detecta el cierre y reconecta solo — se re-registra contra los datos ya
restaurados sin reiniciar el backend ni afectar otras organizaciones.

Uso:
    python scripts/force_disconnect_org.py <organization_id>

Nota: requiere que el backend esté corriendo con Redis configurado
(REDIS_URL). Si no hay ningún worker escuchando, no hace nada — no falla,
pero avisa que 0 workers recibieron el mensaje.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import redis.asyncio as aioredis
from app.core.config import settings


async def main(organization_id: str) -> None:
    if not settings.REDIS_URL:
        print("✗ REDIS_URL no está configurado. Este script requiere Redis (modo multi-worker).")
        print("  En modo single-worker, un restart normal del backend ya resuelve esto.")
        return

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        payload = {
            "_target": "force_disconnect",
            "_origin_worker": "script:force_disconnect_org",
            "organization_id": organization_id,
            "reason": "Reconexión forzada tras restore de BD",
        }
        channel = f"org:{organization_id}"
        subscribers = await redis_client.publish(channel, json.dumps(payload))

        print(f"Mensaje publicado a '{channel}'. Workers que lo recibieron: {subscribers}")
        if subscribers == 0:
            print(
                "⚠ Ningún worker está suscrito a ese canal. Un worker solo se suscribe "
                "mientras tiene al menos una conexión local de esa organización, así que "
                "esto es normal si ya no queda ninguna workstation de esta org conectada. "
                "Si esperabas que hubiera conexiones vivas, verificá que el backend esté corriendo."
            )
        else:
            print("✓ Las workstations de esta organización deberían reconectar en unos segundos.")
    finally:
        await redis_client.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python scripts/force_disconnect_org.py <organization_id>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
