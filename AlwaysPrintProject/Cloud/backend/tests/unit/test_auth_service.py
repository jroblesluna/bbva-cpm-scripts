"""
Tests unitarios para AuthService.

Verifica:
- Hashing y verificación de contraseñas
- Generación y validación de tokens JWT
- Autenticación de usuarios
- Creación de tokens para usuarios
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import uuid

from app.services.auth import AuthService
from app.models.user import User, UserRole
from app.core.config import settings


class TestPasswordHashing:
    """Tests para hashing y verificación de contraseñas."""
    
    def test_hash_password_genera_hash_valido(self):
        """WHEN se hashea una contraseña, THEN se genera un hash bcrypt válido."""
        password = "mi_contraseña_segura_123"
        hashed = AuthService.hash_password(password)
        
        # Verificar que el hash comienza con $2b$ (bcrypt)
        assert hashed.startswith("$2b$")
        # Verificar que el hash es diferente de la contraseña original
        assert hashed != password
        # Verificar que el hash tiene longitud apropiada (60 caracteres para bcrypt)
        assert len(hashed) == 60
    
    def test_hash_password_genera_hashes_diferentes_para_misma_contraseña(self):
        """WHEN se hashea la misma contraseña dos veces, THEN se generan hashes diferentes (salt aleatorio)."""
        password = "contraseña_test"
        hash1 = AuthService.hash_password(password)
        hash2 = AuthService.hash_password(password)
        
        # Los hashes deben ser diferentes debido al salt aleatorio
        assert hash1 != hash2
    
    def test_verify_password_retorna_true_para_contraseña_correcta(self):
        """WHEN se verifica una contraseña correcta, THEN retorna True."""
        password = "contraseña_correcta"
        hashed = AuthService.hash_password(password)
        
        assert AuthService.verify_password(password, hashed) is True
    
    def test_verify_password_retorna_false_para_contraseña_incorrecta(self):
        """WHEN se verifica una contraseña incorrecta, THEN retorna False."""
        password = "contraseña_correcta"
        hashed = AuthService.hash_password(password)
        
        assert AuthService.verify_password("contraseña_incorrecta", hashed) is False
    
    def test_verify_password_es_case_sensitive(self):
        """WHEN se verifica una contraseña con diferente capitalización, THEN retorna False."""
        password = "ContraseñaTest"
        hashed = AuthService.hash_password(password)
        
        assert AuthService.verify_password("contraseñatest", hashed) is False
        assert AuthService.verify_password("CONTRASEÑATEST", hashed) is False


class TestJWTTokens:
    """Tests para generación y validación de tokens JWT."""
    
    def test_create_access_token_genera_token_valido(self):
        """WHEN se crea un access token, THEN se genera un JWT válido."""
        data = {
            "sub": str(uuid.uuid4()),
            "email": "test@example.com",
            "role": "operator"
        }
        
        token = AuthService.create_access_token(data)
        
        # Verificar que el token no está vacío
        assert token
        # Verificar que el token tiene formato JWT (3 partes separadas por puntos)
        assert len(token.split(".")) == 3
    
    def test_create_access_token_incluye_datos_correctos(self):
        """WHEN se crea un access token, THEN incluye todos los datos proporcionados."""
        user_id = str(uuid.uuid4())
        data = {
            "sub": user_id,
            "email": "operator@bbva.com",
            "role": "operator",
            "account_id": str(uuid.uuid4())
        }
        
        token = AuthService.create_access_token(data)
        payload = AuthService.decode_token(token)
        
        assert payload is not None
        assert payload["sub"] == user_id
        assert payload["email"] == "operator@bbva.com"
        assert payload["role"] == "operator"
        assert "account_id" in payload
        assert "exp" in payload
        assert "iat" in payload
    
    def test_create_access_token_con_expiracion_personalizada(self):
        """WHEN se crea un token con expiración personalizada, THEN respeta el tiempo especificado."""
        data = {"sub": str(uuid.uuid4())}
        expires_delta = timedelta(minutes=30)
        
        token = AuthService.create_access_token(data, expires_delta)
        payload = AuthService.decode_token(token)
        
        assert payload is not None
        # Verificar que la expiración está aproximadamente en 30 minutos
        exp_time = datetime.utcfromtimestamp(payload["exp"])
        expected_time = datetime.utcnow() + expires_delta
        # Permitir 5 segundos de diferencia por tiempo de ejecución
        assert abs((exp_time - expected_time).total_seconds()) < 5
    
    def test_create_refresh_token_genera_token_valido(self):
        """WHEN se crea un refresh token, THEN se genera un JWT válido con type=refresh."""
        data = {"sub": str(uuid.uuid4())}
        
        token = AuthService.create_refresh_token(data)
        payload = AuthService.decode_token(token)
        
        assert payload is not None
        assert payload["type"] == "refresh"
        assert "sub" in payload
        assert "exp" in payload
        assert "iat" in payload
    
    def test_decode_token_retorna_payload_para_token_valido(self):
        """WHEN se decodifica un token válido, THEN retorna el payload."""
        data = {"sub": str(uuid.uuid4()), "email": "test@example.com"}
        token = AuthService.create_access_token(data)
        
        payload = AuthService.decode_token(token)
        
        assert payload is not None
        assert payload["sub"] == data["sub"]
        assert payload["email"] == data["email"]
    
    def test_decode_token_retorna_none_para_token_invalido(self):
        """WHEN se decodifica un token inválido, THEN retorna None."""
        invalid_token = "token.invalido.xyz"
        
        payload = AuthService.decode_token(invalid_token)
        
        assert payload is None
    
    def test_decode_token_retorna_none_para_token_expirado(self):
        """WHEN se decodifica un token expirado, THEN retorna None."""
        data = {"sub": str(uuid.uuid4())}
        # Crear token que expira en -1 minuto (ya expirado)
        expires_delta = timedelta(minutes=-1)
        token = AuthService.create_access_token(data, expires_delta)
        
        payload = AuthService.decode_token(token)
        
        assert payload is None
    
    def test_verify_token_retorna_true_para_token_valido(self):
        """WHEN se verifica un token válido, THEN retorna True."""
        data = {"sub": str(uuid.uuid4())}
        token = AuthService.create_access_token(data)
        
        assert AuthService.verify_token(token) is True
    
    def test_verify_token_retorna_false_para_token_invalido(self):
        """WHEN se verifica un token inválido, THEN retorna False."""
        invalid_token = "token.invalido.xyz"
        
        assert AuthService.verify_token(invalid_token) is False
    
    def test_validate_refresh_token_retorna_user_id_para_token_valido(self):
        """WHEN se valida un refresh token válido, THEN retorna el user_id."""
        user_id = str(uuid.uuid4())
        data = {"sub": user_id, "type": "refresh"}
        token = AuthService.create_refresh_token(data)
        
        result = AuthService.validate_refresh_token(token)
        
        assert result == user_id
    
    def test_validate_refresh_token_retorna_none_para_access_token(self):
        """WHEN se valida un access token como refresh token, THEN retorna None."""
        user_id = str(uuid.uuid4())
        data = {"sub": user_id}
        token = AuthService.create_access_token(data)
        
        result = AuthService.validate_refresh_token(token)
        
        assert result is None


class TestAuthenticateUser:
    """Tests para autenticación de usuarios."""
    
    def test_authenticate_user_retorna_usuario_para_credenciales_validas(self, db: Session):
        """WHEN se autentican credenciales válidas, THEN retorna el usuario."""
        # Crear cuenta de prueba (requerida por FK)
        from app.models.account import Account
        account = Account(
            id=uuid.uuid4(),
            name="Test Account",
            is_active=True
        )
        db.add(account)
        db.commit()

        # Crear usuario de prueba
        password = "contraseña_segura_123"
        user = User(
            id=uuid.uuid4(),
            email="operator@bbva.com",
            password_hash=AuthService.hash_password(password),
            full_name="Operador Test",
            role=UserRole.OPERATOR,
            account_id=account.id,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Autenticar
        authenticated_user = AuthService.authenticate_user(
            db, "operator@bbva.com", password
        )
        
        assert authenticated_user is not None
        assert authenticated_user.id == user.id
        assert authenticated_user.email == user.email
    
    def test_authenticate_user_retorna_none_para_email_inexistente(self, db: Session):
        """WHEN se autentica con email inexistente, THEN retorna None."""
        result = AuthService.authenticate_user(
            db, "noexiste@example.com", "cualquier_contraseña"
        )
        
        assert result is None
    
    def test_authenticate_user_retorna_none_para_contraseña_incorrecta(self, db: Session):
        """WHEN se autentica con contraseña incorrecta, THEN retorna None."""
        # Crear usuario de prueba
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=AuthService.hash_password("contraseña_correcta"),
            full_name="Test User",
            role=UserRole.OPERATOR,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Intentar autenticar con contraseña incorrecta
        result = AuthService.authenticate_user(
            db, "test@example.com", "contraseña_incorrecta"
        )
        
        assert result is None
    
    def test_authenticate_user_retorna_none_para_usuario_inactivo(self, db: Session):
        """WHEN se autentica un usuario inactivo, THEN retorna None."""
        # Crear usuario inactivo
        password = "contraseña_test"
        user = User(
            id=uuid.uuid4(),
            email="inactivo@example.com",
            password_hash=AuthService.hash_password(password),
            full_name="Inactivo User",
            role=UserRole.OPERATOR,
            is_active=False  # Usuario desactivado
        )
        db.add(user)
        db.commit()
        
        # Intentar autenticar
        result = AuthService.authenticate_user(
            db, "inactivo@example.com", password
        )
        
        assert result is None


class TestGetUserFromToken:
    """Tests para obtener usuario desde token JWT."""
    
    def test_get_user_from_token_retorna_usuario_para_token_valido(self, db: Session):
        """WHEN se obtiene usuario desde token válido, THEN retorna el usuario."""
        # Crear usuario de prueba
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=AuthService.hash_password("password"),
            full_name="Test User",
            role=UserRole.OPERATOR,
            is_active=True
        )
        db.add(user)
        db.commit()
        
        # Crear token para el usuario
        token = AuthService.create_access_token({
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value
        })
        
        # Obtener usuario desde token
        result = AuthService.get_user_from_token(db, token)
        
        assert result is not None
        assert result.id == user.id
        assert result.email == user.email
    
    def test_get_user_from_token_retorna_none_para_token_invalido(self, db: Session):
        """WHEN se obtiene usuario desde token inválido, THEN retorna None."""
        invalid_token = "token.invalido.xyz"
        
        result = AuthService.get_user_from_token(db, invalid_token)
        
        assert result is None
    
    def test_get_user_from_token_retorna_none_para_usuario_inexistente(self, db: Session):
        """WHEN el usuario del token no existe en BD, THEN retorna None."""
        # Crear token con ID de usuario inexistente
        token = AuthService.create_access_token({
            "sub": str(uuid.uuid4()),
            "email": "noexiste@example.com"
        })
        
        result = AuthService.get_user_from_token(db, token)
        
        assert result is None
    
    def test_get_user_from_token_retorna_none_para_usuario_inactivo(self, db: Session):
        """WHEN el usuario del token está inactivo, THEN retorna None."""
        # Crear usuario inactivo
        user = User(
            id=uuid.uuid4(),
            email="inactivo@example.com",
            password_hash=AuthService.hash_password("password"),
            full_name="Inactivo User",
            role=UserRole.OPERATOR,
            is_active=False
        )
        db.add(user)
        db.commit()
        
        # Crear token para el usuario
        token = AuthService.create_access_token({
            "sub": str(user.id),
            "email": user.email
        })
        
        result = AuthService.get_user_from_token(db, token)
        
        assert result is None


class TestCreateTokensForUser:
    """Tests para creación de tokens completos para usuario."""
    
    def test_create_tokens_for_user_retorna_access_y_refresh_tokens(self):
        """WHEN se crean tokens para usuario, THEN retorna access_token y refresh_token."""
        user = User(
            id=uuid.uuid4(),
            email="operator@bbva.com",
            password_hash=AuthService.hash_password("password"),
            role=UserRole.OPERATOR,
            account_id=uuid.uuid4(),
            is_active=True
        )
        
        tokens = AuthService.create_tokens_for_user(user)
        
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert "token_type" in tokens
        assert "expires_in" in tokens
        assert tokens["token_type"] == "bearer"
    
    def test_create_tokens_for_user_access_token_contiene_datos_correctos(self):
        """WHEN se crea access token, THEN contiene todos los datos del usuario."""
        user = User(
            id=uuid.uuid4(),
            email="admin@system.com",
            password_hash=AuthService.hash_password("password"),
            role=UserRole.ADMIN,
            account_id=None,  # Admin no tiene account_id
            is_active=True
        )
        
        tokens = AuthService.create_tokens_for_user(user)
        payload = AuthService.decode_token(tokens["access_token"])
        
        assert payload is not None
        assert payload["sub"] == str(user.id)
        assert payload["email"] == user.email
        assert payload["role"] == "admin"
        assert payload["account_id"] is None
    
    def test_create_tokens_for_user_refresh_token_es_valido(self):
        """WHEN se crea refresh token, THEN es válido y contiene type=refresh."""
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=AuthService.hash_password("password"),
            role=UserRole.READONLY,
            is_active=True
        )
        
        tokens = AuthService.create_tokens_for_user(user)
        user_id = AuthService.validate_refresh_token(tokens["refresh_token"])
        
        assert user_id == str(user.id)
