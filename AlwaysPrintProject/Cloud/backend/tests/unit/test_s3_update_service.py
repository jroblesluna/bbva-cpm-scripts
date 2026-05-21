"""
Tests unitarios para S3UpdateService.

Verifica el comportamiento del servicio de integración con S3
para actualizaciones automáticas del MSI.
"""

import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError

from app.services.s3_update_service import S3UpdateService


class TestS3UpdateServiceGetMsiMetadata:
    """Tests para el método get_msi_metadata()."""

    @patch('app.services.s3_update_service.boto3.client')
    def test_retorna_metadata_completa_cuando_s3_responde(self, mock_boto_client):
        """Verifica que se extraen correctamente todos los campos de metadata."""
        # Configurar mock de S3
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_object.return_value = {
            'Metadata': {
                'version': '2.1.0',
                'build-date': '2026-06-01T10:30:00Z',
                'commit-hash': 'abc1234',
            },
            'ContentLength': 15728640,
        }

        servicio = S3UpdateService()
        resultado = servicio.get_msi_metadata()

        assert resultado['version'] == '2.1.0'
        assert resultado['build_date'] == '2026-06-01T10:30:00Z'
        assert resultado['commit_hash'] == 'abc1234'
        assert resultado['file_size'] == 15728640

    @patch('app.services.s3_update_service.boto3.client')
    def test_retorna_valores_por_defecto_cuando_metadata_vacia(self, mock_boto_client):
        """Verifica que se usan valores por defecto cuando la metadata no tiene campos."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_object.return_value = {
            'Metadata': {},
            'ContentLength': 0,
        }

        servicio = S3UpdateService()
        resultado = servicio.get_msi_metadata()

        assert resultado['version'] == 'unknown'
        assert resultado['build_date'] == ''
        assert resultado['commit_hash'] == ''
        assert resultado['file_size'] == 0

    @patch('app.services.s3_update_service.boto3.client')
    def test_propaga_client_error_cuando_objeto_no_existe(self, mock_boto_client):
        """Verifica que se propaga ClientError cuando el objeto S3 no existe."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_object.side_effect = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'HeadObject'
        )

        servicio = S3UpdateService()

        with pytest.raises(ClientError) as exc_info:
            servicio.get_msi_metadata()

        assert exc_info.value.response['Error']['Code'] == '404'

    @patch('app.services.s3_update_service.boto3.client')
    def test_propaga_client_error_cuando_s3_no_disponible(self, mock_boto_client):
        """Verifica que se propaga ClientError cuando S3 no está disponible."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_object.side_effect = ClientError(
            {'Error': {'Code': '503', 'Message': 'Service Unavailable'}},
            'HeadObject'
        )

        servicio = S3UpdateService()

        with pytest.raises(ClientError):
            servicio.get_msi_metadata()


class TestS3UpdateServiceGenerateDownloadUrl:
    """Tests para el método generate_download_url()."""

    @patch('app.services.s3_update_service.boto3.client')
    def test_genera_url_con_expiracion_por_defecto(self, mock_boto_client):
        """Verifica que se genera URL presigned con expiración de 1 hora."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = 'https://s3.amazonaws.com/presigned-url'

        servicio = S3UpdateService()
        url = servicio.generate_download_url()

        assert url == 'https://s3.amazonaws.com/presigned-url'
        mock_s3.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'alwaysprint-prod-artifacts', 'Key': 'latest/AlwaysPrint.msi'},
            ExpiresIn=3600
        )

    @patch('app.services.s3_update_service.boto3.client')
    def test_genera_url_con_expiracion_personalizada(self, mock_boto_client):
        """Verifica que se respeta el parámetro expires_in personalizado."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = 'https://s3.amazonaws.com/custom-url'

        servicio = S3UpdateService()
        url = servicio.generate_download_url(expires_in=7200)

        assert url == 'https://s3.amazonaws.com/custom-url'
        mock_s3.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'alwaysprint-prod-artifacts', 'Key': 'latest/AlwaysPrint.msi'},
            ExpiresIn=7200
        )

    @patch('app.services.s3_update_service.boto3.client')
    def test_propaga_client_error_al_generar_url(self, mock_boto_client):
        """Verifica que se propaga ClientError si falla la generación de URL."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.generate_presigned_url.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}},
            'GeneratePresignedUrl'
        )

        servicio = S3UpdateService()

        with pytest.raises(ClientError) as exc_info:
            servicio.generate_download_url()

        assert exc_info.value.response['Error']['Code'] == 'AccessDenied'
