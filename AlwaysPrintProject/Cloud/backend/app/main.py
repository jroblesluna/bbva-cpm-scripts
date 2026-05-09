"""
Punto de entrada principal de la aplicación FastAPI
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="AlwaysPrint Cloud Management API",
    description="Sistema de gestión centralizada de estaciones AlwaysPrint",
    version="0.1.0",
)

# Configuración CORS (se configurará con variables de entorno)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configurar desde variables de entorno
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Endpoint raíz para verificar que el servidor está funcionando"""
    return {
        "message": "AlwaysPrint Cloud Management API",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Endpoint de health check"""
    return {"status": "healthy"}
