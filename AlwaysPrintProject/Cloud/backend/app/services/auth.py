"""
Servicio de autenticación para AlwaysPrint Cloud Management.

Este módulo proporciona funcionalidades de:
- Hashing y verificación de contraseñas con bcrypt
- Generación y validación de tokens JWT
- Validación de credenciales de usuario
- Gestión de refresh tokens

Requisitos implementados: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
import hashlib

from app.core.config import settings
from app.models.user import User, UserRole


# === CONFIGURACIÓN DE BCRYPT ===
# Cost factor 12 según requisito 5.2
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


class AuthService:
    """
    Servicio de autenticación del sistema.
    
    Proporciona métodos estáticos para:
    - Hashing de contraseñas
    - Validación de credenciales
    - Generación de tokens JWT
    - Validación de tokens JWT
    """
    
    # === HASHING DE CONTRASEÑAS ===
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hashea una contraseña usando bcrypt con cost factor 12.
        
        Para evitar el límite de 72 bytes de bcrypt, primero se hashea
        la contraseña con SHA-256, resultando en un string hexadecimal
        de 64 caracteres (32 bytes), que luego se hashea con bcrypt.
        
        Este enfoque permite contraseñas de cualquier longitud y
        caracteres Unicode sin problemas de truncamiento.
        
        Args:
            password: Contraseña en texto plano
            
        Returns:
            Hash bcrypt de la contraseña
            
        Ejemplo:
            >>> hashed = AuthService.hash_password("mi_contraseña_segura")
            >>> print(hashed)
            $2b$12$...
        """
        # Pre-hashear con SHA-256 para evitar límite de 72 bytes de bcrypt
        # SHA-256 produce un hash de 32 bytes (64 caracteres hex)
        password_sha256 = hashlib.sha256(password.encode('utf-8')).hexdigest()
        
        # Hashear el SHA-256 con bcrypt
        return pwd_context.hash(password_sha256)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verifica si una contraseña en texto plano coincide con su hash.
        
        Aplica el mismo pre-hashing SHA-256 antes de verificar con bcrypt.
        
        Args:
            plain_password: Contraseña en texto plano
            hashed_password: Hash bcrypt de la contraseña
            
        Returns:
            True si la contraseña es correcta, False en caso contrario
            
        Ejemplo:
            >>> hashed = AuthService.hash_password("mi_contraseña")
            >>> AuthService.verify_password("mi_contraseña", hashed)
            True
            >>> AuthService.verify_password("contraseña_incorrecta", hashed)
            False
        """
        # Pre-hashear con SHA-256 (mismo proceso que en hash_password)
        password_sha256 = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
        
        # Verificar con bcrypt
        return pwd_context.verify(password_sha256, hashed_password)
    
    # === GENERACIÓN DE TOKENS JWT ===
    
    @staticmethod
    def create_access_token(
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Genera un token JWT de acceso.
        
        El token incluye:
        - sub: ID del usuario
        - email: Email del usuario
        - role: Rol del usuario (admin, operator, readonly)
        - organization_id: ID de la organización (null para admin)
        - exp: Timestamp de expiración (24 horas por defecto)
        - iat: Timestamp de emisión
        
        Args:
            data: Diccionario con datos a incluir en el token
            expires_delta: Tiempo de expiración personalizado (opcional)
            
        Returns:
            Token JWT codificado
            
        Ejemplo:
            >>> token = AuthService.create_access_token({
            ...     "sub": str(user.id),
            ...     "email": user.email,
            ...     "role": user.role.value,
            ...     "organization_id": str(user.organization_id) if user.organization_id else None
            ... })
        """
        to_encode = data.copy()
        
        # Calcular tiempo de expiración
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            # Por defecto: 24 horas (1440 minutos) según requisito 5.3
            expire = datetime.utcnow() + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
        
        # Agregar claims estándar
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow()
        })
        
        # Codificar token
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        
        return encoded_jwt
    
    @staticmethod
    def create_refresh_token(
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Genera un token JWT de refresh para renovación.
        
        Los refresh tokens tienen mayor duración (7 días por defecto)
        y se usan para obtener nuevos access tokens sin re-autenticarse.
        
        Args:
            data: Diccionario con datos a incluir en el token
            expires_delta: Tiempo de expiración personalizado (opcional)
            
        Returns:
            Token JWT de refresh codificado
            
        Ejemplo:
            >>> refresh_token = AuthService.create_refresh_token({
            ...     "sub": str(user.id),
            ...     "type": "refresh"
            ... })
        """
        to_encode = data.copy()
        
        # Calcular tiempo de expiración
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            # Por defecto: 7 días para refresh tokens
            expire = datetime.utcnow() + timedelta(days=7)
        
        # Agregar claims estándar
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "refresh"  # Identificar como refresh token
        })
        
        # Codificar token
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        
        return encoded_jwt
    
    # === VALIDACIÓN DE TOKENS JWT ===
    
    @staticmethod
    def decode_token(token: str) -> Optional[Dict[str, Any]]:
        """
        Decodifica y valida un token JWT.
        
        Args:
            token: Token JWT a decodificar
            
        Returns:
            Diccionario con los datos del token si es válido, None si es inválido
            
        Ejemplo:
            >>> payload = AuthService.decode_token(token)
            >>> if payload:
            ...     user_id = payload.get("sub")
            ...     role = payload.get("role")
        """
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )
            return payload
        except JWTError:
            return None
    
    @staticmethod
    def verify_token(token: str) -> bool:
        """
        Verifica si un token JWT es válido.
        
        Args:
            token: Token JWT a verificar
            
        Returns:
            True si el token es válido, False en caso contrario
            
        Ejemplo:
            >>> if AuthService.verify_token(token):
            ...     print("Token válido")
            ... else:
            ...     print("Token inválido o expirado")
        """
        payload = AuthService.decode_token(token)
        return payload is not None
    
    # === VALIDACIÓN DE CREDENCIALES ===
    
    @staticmethod
    def authenticate_user(
        db: Session,
        email: str,
        password: str
    ) -> Optional[User]:
        """
        Autentica un usuario con email y contraseña.
        
        Verifica que:
        1. El usuario existe
        2. El usuario está activo
        3. La contraseña es correcta
        
        Args:
            db: Sesión de base de datos
            email: Email del usuario
            password: Contraseña en texto plano
            
        Returns:
            Objeto User si las credenciales son válidas, None en caso contrario
            
        Nota:
            Por seguridad, no se distingue entre "usuario no existe" y
            "contraseña incorrecta" para evitar enumeración de usuarios.
            
        Ejemplo:
            >>> user = AuthService.authenticate_user(db, "operator@bbva.com", "password123")
            >>> if user:
            ...     print(f"Autenticado: {user.email}")
            ... else:
            ...     print("Credenciales inválidas")
        """
        # Buscar usuario por email
        user = db.query(User).filter(User.email == email).first()
        
        # Verificar que el usuario existe
        if not user:
            return None
        
        # Verificar que el usuario está activo
        if not user.is_active:
            return None
        
        # Verificar contraseña
        if not AuthService.verify_password(password, user.password_hash):
            return None
        
        return user
    
    @staticmethod
    def get_user_from_token(db: Session, token: str) -> Optional[User]:
        """
        Obtiene un usuario a partir de un token JWT.
        
        Args:
            db: Sesión de base de datos
            token: Token JWT
            
        Returns:
            Objeto User si el token es válido, None en caso contrario
            
        Ejemplo:
            >>> user = AuthService.get_user_from_token(db, token)
            >>> if user:
            ...     print(f"Usuario: {user.email}, Rol: {user.role}")
        """
        # Decodificar token
        payload = AuthService.decode_token(token)
        if not payload:
            return None
        
        # Obtener ID de usuario del token
        user_id: str = payload.get("sub")
        if not user_id:
            return None
        
        # Buscar usuario en base de datos
        user = db.query(User).filter(User.id == user_id).first()
        
        # Verificar que el usuario está activo
        if user and not user.is_active:
            return None
        
        return user
    
    # === UTILIDADES ===
    
    @staticmethod
    def create_tokens_for_user(user: User) -> Dict[str, Any]:
        """
        Crea access token y refresh token para un usuario.
        
        Args:
            user: Objeto User
            
        Returns:
            Diccionario con access_token, refresh_token, token_type y expires_in
            
        Ejemplo:
            >>> tokens = AuthService.create_tokens_for_user(user)
            >>> print(tokens["access_token"])
            >>> print(tokens["refresh_token"])
        """
        # Datos a incluir en el token
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
            "organization_id": str(user.organization_id) if user.organization_id else None
        }
        
        # Crear access token
        access_token = AuthService.create_access_token(token_data)
        
        # Crear refresh token
        refresh_token = AuthService.create_refresh_token({
            "sub": str(user.id),
            "type": "refresh"
        })
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # en segundos
        }
    
    @staticmethod
    def validate_refresh_token(token: str) -> Optional[str]:
        """
        Valida un refresh token y extrae el user_id.
        
        Args:
            token: Refresh token JWT
            
        Returns:
            ID del usuario si el token es válido, None en caso contrario
            
        Ejemplo:
            >>> user_id = AuthService.validate_refresh_token(refresh_token)
            >>> if user_id:
            ...     # Generar nuevo access token
            ...     user = db.query(User).filter(User.id == user_id).first()
            ...     new_token = AuthService.create_access_token({...})
        """
        payload = AuthService.decode_token(token)
        if not payload:
            return None
        
        # Verificar que es un refresh token
        if payload.get("type") != "refresh":
            return None
        
        # Extraer user_id
        user_id = payload.get("sub")
        return user_id
