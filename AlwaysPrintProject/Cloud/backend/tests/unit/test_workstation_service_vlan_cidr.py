"""
Tests unitarios para el método detect_or_create_vlan_for_cidr de WorkstationService.

Verifica la lógica de auto-asignación de VLAN por CIDR:
- Búsqueda de VLAN existente con el CIDR
- Auto-creación de VLAN cuando no existe
- Normalización de CIDR
- Aislamiento por organización (tenant isolation)
- Manejo de race condition (IntegrityError)
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.vlan import VLAN
from app.services.workstation import WorkstationService


class TestDetectOrCreateVlanForCidr:
    """Tests para detect_or_create_vlan_for_cidr."""

    def setup_method(self):
        """Configuración común para cada test."""
        self.service = WorkstationService()
        self.org_id = str(uuid.uuid4())

    def test_retorna_vlan_existente_con_cidr(self):
        """Si ya existe una VLAN con el CIDR, retorna su UUID."""
        vlan_id = uuid.uuid4()
        mock_vlan = MagicMock(spec=VLAN)
        mock_vlan.id = vlan_id
        mock_vlan.cidr_ranges = ["192.168.1.0/24"]

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.all.return_value = [mock_vlan]
        mock_db.query.return_value.filter_by.return_value = mock_query

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "192.168.1.0/24"
        )

        assert resultado == str(vlan_id)
        # No se debe crear VLAN nueva
        mock_db.add.assert_not_called()

    def test_normaliza_cidr_antes_de_buscar(self):
        """El CIDR se normaliza antes de buscar (ej: 192.168.1.50/24 → 192.168.1.0/24)."""
        vlan_id = uuid.uuid4()
        mock_vlan = MagicMock(spec=VLAN)
        mock_vlan.id = vlan_id
        mock_vlan.cidr_ranges = ["192.168.1.0/24"]

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.all.return_value = [mock_vlan]
        mock_db.query.return_value.filter_by.return_value = mock_query

        # Enviar CIDR no normalizado (host bits encendidos)
        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "192.168.1.50/24"
        )

        assert resultado == str(vlan_id)

    def test_crea_vlan_cuando_no_existe(self):
        """Si no existe VLAN con el CIDR, crea una nueva."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        # Primera llamada: _find_vlan_with_cidr (no encuentra)
        # Segunda llamada: validate_cidr_uniqueness (no hay conflicto)
        mock_query.all.side_effect = [[], []]
        mock_db.query.return_value.filter_by.return_value = mock_query

        # Simular que flush asigna un ID
        new_vlan_id = uuid.uuid4()

        def side_effect_add(vlan):
            vlan.id = new_vlan_id

        mock_db.add.side_effect = side_effect_add

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "10.0.0.0/16"
        )

        assert resultado == str(new_vlan_id)
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

        # Verificar que la VLAN creada tiene el nombre y cidr_ranges correctos
        vlan_creada = mock_db.add.call_args[0][0]
        assert vlan_creada.name == "VLAN_10.0.0.0/16"
        assert vlan_creada.cidr_ranges == ["10.0.0.0/16"]
        assert vlan_creada.organization_id == self.org_id

    def test_maneja_race_condition_con_reintento(self):
        """Si hay IntegrityError al crear, reintenta búsqueda."""
        vlan_id = uuid.uuid4()
        mock_vlan = MagicMock(spec=VLAN)
        mock_vlan.id = vlan_id
        mock_vlan.cidr_ranges = ["172.16.0.0/12"]

        mock_db = MagicMock()
        mock_query = MagicMock()

        # Primera búsqueda (_find_vlan_with_cidr): no encuentra nada
        # Segunda búsqueda (validate_cidr_uniqueness): no encuentra conflicto
        # Tercera búsqueda (_find_vlan_with_cidr tras race condition): encuentra la VLAN
        mock_query.all.side_effect = [[], [], [mock_vlan]]
        mock_db.query.return_value.filter_by.return_value = mock_query

        # Simular IntegrityError al hacer flush
        mock_db.flush.side_effect = IntegrityError(
            "UNIQUE constraint failed", params=None, orig=Exception()
        )

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "172.16.0.0/12"
        )

        assert resultado == str(vlan_id)
        mock_db.rollback.assert_called_once()

    def test_retorna_none_para_cidr_invalido(self):
        """Si el CIDR es inválido, retorna None."""
        mock_db = MagicMock()

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "no-es-un-cidr"
        )

        assert resultado is None

    def test_no_retorna_vlan_de_otra_organizacion(self):
        """Solo busca VLANs de la organización indicada (tenant isolation)."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        # Primera llamada: _find_vlan_with_cidr (no encuentra)
        # Segunda llamada: validate_cidr_uniqueness (no hay conflicto)
        mock_query.all.side_effect = [[], []]
        mock_db.query.return_value.filter_by.return_value = mock_query

        new_vlan_id = uuid.uuid4()

        def side_effect_add(vlan):
            vlan.id = new_vlan_id

        mock_db.add.side_effect = side_effect_add

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "192.168.1.0/24"
        )

        # Verificar que se filtró por organization_id
        mock_db.query.return_value.filter_by.assert_called_with(
            organization_id=self.org_id
        )
        assert resultado == str(new_vlan_id)

    def test_vlan_con_cidr_ranges_none_no_falla(self):
        """Si una VLAN tiene cidr_ranges=None, no causa error."""
        mock_vlan_sin_cidr = MagicMock(spec=VLAN)
        mock_vlan_sin_cidr.id = uuid.uuid4()
        mock_vlan_sin_cidr.cidr_ranges = None

        mock_vlan_con_cidr = MagicMock(spec=VLAN)
        mock_vlan_con_cidr.id = uuid.uuid4()
        mock_vlan_con_cidr.cidr_ranges = ["192.168.1.0/24"]

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.all.return_value = [mock_vlan_sin_cidr, mock_vlan_con_cidr]
        mock_db.query.return_value.filter_by.return_value = mock_query

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "192.168.1.0/24"
        )

        assert resultado == str(mock_vlan_con_cidr.id)

    def test_vlan_con_multiples_cidrs_encuentra_match(self):
        """Si una VLAN tiene múltiples CIDRs, encuentra el match correcto."""
        vlan_id = uuid.uuid4()
        mock_vlan = MagicMock(spec=VLAN)
        mock_vlan.id = vlan_id
        mock_vlan.cidr_ranges = ["10.0.0.0/8", "192.168.1.0/24", "172.16.0.0/12"]

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.all.return_value = [mock_vlan]
        mock_db.query.return_value.filter_by.return_value = mock_query

        resultado = self.service.detect_or_create_vlan_for_cidr(
            mock_db, self.org_id, "172.16.0.0/12"
        )

        assert resultado == str(vlan_id)
