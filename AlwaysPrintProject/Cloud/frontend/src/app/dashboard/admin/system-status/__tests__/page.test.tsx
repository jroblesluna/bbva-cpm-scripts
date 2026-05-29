/**
 * Tests del dashboard de estado del sistema.
 *
 * Verifica: estado vacío, renderizado de gauges con valores límite,
 * alertas (máximo 10 visibles), colores de umbrales, banner crítico,
 * y estado de carga del botón de recolección.
 *
 * Validates: Requirements 6.1, 6.2, 8.1, 8.8
 */

import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { StatusSnapshot } from '@/types/system-status';

// === MOCKS ===

// Mock de next-intl: retorna la key como texto
vi.mock('next-intl', () => ({
  useTranslations: () => {
    const t = (key: string, params?: Record<string, unknown>) => {
      if (params) {
        let result = key;
        for (const [k, v] of Object.entries(params)) {
          result += ` ${k}:${v}`;
        }
        return result;
      }
      return key;
    };
    return t;
  },
}));

// Mock de next/navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock de useAuth: simula usuario admin por defecto
const mockIsAdmin = vi.fn(() => true);
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAdmin: mockIsAdmin,
    isLoading: false,
    isAuthenticated: true,
  }),
}));

// Mock de useToast
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Mock de las funciones API
const mockGetSystemStatusCurrent = vi.fn();
const mockTriggerCollection = vi.fn();
vi.mock('@/lib/api/system-status', () => ({
  getSystemStatusCurrent: (...args: unknown[]) => mockGetSystemStatusCurrent(...args),
  triggerCollection: (...args: unknown[]) => mockTriggerCollection(...args),
}));

// Mock del componente HistoryTab para evitar dependencias complejas
vi.mock('../components/HistoryTab', () => ({
  default: () => <div data-testid="history-tab">HistoryTab</div>,
}));

// Importar el componente después de los mocks
import SystemStatusPage from '../page';

// === HELPERS ===

/**
 * Genera un snapshot de prueba con valores configurables.
 */
function createMockSnapshot(overrides: Partial<StatusSnapshot> = {}): StatusSnapshot {
  return {
    id: 'test-id-123',
    timestamp: '2024-06-15T12:00:00Z',
    overall_status: 'healthy',
    os_metrics: {
      memory_total_mb: 8192,
      memory_used_mb: 4096,
      memory_available_mb: 4096,
      memory_percent: 50,
      disk_total_mb: 102400,
      disk_used_mb: 51200,
      disk_available_mb: 51200,
      disk_percent: 50,
      cpu_percent: 50,
      swap_total_mb: 4096,
      swap_used_mb: 1024,
      swap_available_mb: 3072,
      uptime_seconds: 86400,
    },
    docker_metrics: [],
    health_checks: [],
    alerts: [],
    ...overrides,
  };
}

// === TESTS ===

describe('SystemStatusPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsAdmin.mockReturnValue(true);
    mockGetSystemStatusCurrent.mockResolvedValue(null);
    mockTriggerCollection.mockResolvedValue(createMockSnapshot());
  });

  // --- Test 1: Estado vacío ---
  describe('Estado vacío', () => {
    it('muestra mensaje de estado vacío y botón de recolección cuando no hay datos', async () => {
      mockGetSystemStatusCurrent.mockResolvedValue(null);

      render(<SystemStatusPage />);

      // Esperar a que se cargue y muestre el estado vacío
      await waitFor(() => {
        expect(screen.getByText('emptyTitle')).toBeInTheDocument();
        expect(screen.getByText('emptyMessage')).toBeInTheDocument();
        // El botón de recolección debe estar presente
        expect(screen.getByText('collectBtn')).toBeInTheDocument();
      });
    });
  });

  // --- Test 2: Gauges con valores límite ---
  describe('Gauges con valores límite', () => {
    it('renderiza gauge con CPU=0%', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          cpu_percent: 0,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByLabelText('cpu: 0%')).toBeInTheDocument();
      });
    });

    it('renderiza gauge con CPU=50%', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          cpu_percent: 50,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByLabelText('cpu: 50%')).toBeInTheDocument();
      });
    });

    it('renderiza gauge con CPU=100%', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          cpu_percent: 100,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByLabelText('cpu: 100%')).toBeInTheDocument();
      });
    });

    it('renderiza gauge con Memory=80% (umbral)', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          memory_percent: 80,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByLabelText('memory: 80%')).toBeInTheDocument();
      });
    });

    it('renderiza gauge con Disk=85% (umbral)', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          disk_percent: 85,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByLabelText('disk: 85%')).toBeInTheDocument();
      });
    });
  });

  // --- Test 3: Alertas máximo 10 ---
  describe('Alertas máximo 10 visibles', () => {
    it('muestra solo 10 alertas cuando hay más de 10, con indicador "+N más"', async () => {
      // Generar 15 alertas
      const alerts = Array.from({ length: 15 }, (_, i) => ({
        metric_name: `metric_${i}`,
        current_value: 95 + i * 0.1,
        threshold: 90,
        severity: 'critical' as const,
      }));

      const snapshot = createMockSnapshot({ alerts });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      // Esperar a que se rendericen las alertas
      await waitFor(() => {
        expect(screen.getByText('metric_0')).toBeInTheDocument();
      });

      // Verificar que se muestran las primeras 10
      for (let i = 0; i < 10; i++) {
        expect(screen.getByText(`metric_${i}`)).toBeInTheDocument();
      }

      // Verificar que la alerta 11 NO se muestra
      expect(screen.queryByText('metric_10')).not.toBeInTheDocument();

      // Verificar indicador "+N más" (la función t retorna la key con params)
      expect(screen.getByText('alertsMore count:5')).toBeInTheDocument();
    });

    it('muestra todas las alertas cuando hay exactamente 10', async () => {
      const alerts = Array.from({ length: 10 }, (_, i) => ({
        metric_name: `alert_${i}`,
        current_value: 91 + i,
        threshold: 90,
        severity: 'critical' as const,
      }));

      const snapshot = createMockSnapshot({ alerts });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByText('alert_0')).toBeInTheDocument();
      });

      // Todas las 10 deben estar visibles
      for (let i = 0; i < 10; i++) {
        expect(screen.getByText(`alert_${i}`)).toBeInTheDocument();
      }

      // No debe haber indicador de "más"
      expect(screen.queryByText(/alertsMore/)).not.toBeInTheDocument();
    });
  });

  // --- Test 4: Colores de umbrales ---
  describe('Colores de umbrales', () => {
    it('aplica color rojo (text-red-500) cuando CPU > 90%', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          cpu_percent: 95,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        const gauge = screen.getByLabelText('cpu: 95%');
        expect(gauge).toBeInTheDocument();
      });

      // Verificar que el texto del valor tiene clase roja
      const valueElement = screen.getByText('95.0%');
      expect(valueElement).toHaveClass('text-red-500');
    });

    it('aplica color amarillo (text-yellow-500) cuando Memory > 80%', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          memory_percent: 85,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        const gauge = screen.getByLabelText('memory: 85%');
        expect(gauge).toBeInTheDocument();
      });

      const valueElement = screen.getByText('85.0%');
      expect(valueElement).toHaveClass('text-yellow-500');
    });

    it('aplica color rojo (text-red-500) cuando Disk > 85%', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          disk_percent: 90,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        const gauge = screen.getByLabelText('disk: 90%');
        expect(gauge).toBeInTheDocument();
      });

      const valueElement = screen.getByText('90.0%');
      expect(valueElement).toHaveClass('text-red-500');
    });

    it('aplica color verde (text-green-500) cuando valores están dentro de umbrales', async () => {
      const snapshot = createMockSnapshot({
        os_metrics: {
          ...createMockSnapshot().os_metrics,
          cpu_percent: 30,
          memory_percent: 40,
          disk_percent: 50,
        },
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByLabelText('cpu: 30%')).toBeInTheDocument();
      });

      expect(screen.getByText('30.0%')).toHaveClass('text-green-500');
      expect(screen.getByText('40.0%')).toHaveClass('text-green-500');
      expect(screen.getByText('50.0%')).toHaveClass('text-green-500');
    });
  });

  // --- Test 5: Banner crítico ---
  describe('Banner crítico', () => {
    it('muestra banner crítico cuando overall_status es "critical"', async () => {
      const snapshot = createMockSnapshot({
        overall_status: 'critical',
        alerts: [
          { metric_name: 'CPU', current_value: 95, threshold: 90, severity: 'critical' },
          { metric_name: 'Disk', current_value: 92, threshold: 85, severity: 'critical' },
        ],
      });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        // El banner usa t('criticalBanner', { count: alerts.length })
        expect(screen.getByText('criticalBanner count:2')).toBeInTheDocument();
      });
    });

    it('no muestra banner cuando overall_status es "healthy"', async () => {
      const snapshot = createMockSnapshot({ overall_status: 'healthy' });
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByText('title')).toBeInTheDocument();
      });

      expect(screen.queryByText(/criticalBanner/)).not.toBeInTheDocument();
    });
  });

  // --- Test 6: Botón de recolección con estado de carga ---
  describe('Botón de recolección - estado de carga', () => {
    it('muestra botón habilitado con texto normal cuando no está recolectando', async () => {
      const snapshot = createMockSnapshot();
      mockGetSystemStatusCurrent.mockResolvedValue(snapshot);

      render(<SystemStatusPage />);

      await waitFor(() => {
        expect(screen.getByText('title')).toBeInTheDocument();
      });

      // El botón de recolección debe estar habilitado
      const buttons = screen.getAllByRole('button');
      const collectButton = buttons.find(
        (btn) => btn.textContent?.includes('collectBtn')
      );
      expect(collectButton).toBeDefined();
      expect(collectButton).not.toBeDisabled();
    });
  });
});
