"""
Property test para el mecanismo de retry con backoff exponencial en descargas S3.

Verifica que para cualquier secuencia de fallos de descarga (errores de red, timeouts,
respuestas 5xx), el mecanismo de retry:
1. Espera exactamente [1000ms, 2000ms, 4000ms] entre reintentos (backoff exponencial)
2. Nunca intenta más de 3 descargas totales
3. En errores 4xx (excepto 429): detiene inmediatamente sin reintentar
4. En éxito en cualquier intento: retorna inmediatamente sin más reintentos

Nota: Se simula la lógica de retry del cliente C# (PushMessageHandler.DownloadWithRetryAsync)
en Python, ya que Hypothesis no corre en .NET.

Feature: push-based-distribution, Property 6: Exponential backoff retry on S3 failure

**Validates: Requirements 2.5, 4.4**
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st


# === Constantes del mecanismo de retry (replicadas del C#) ===

DELAYS_MS = [1000, 2000, 4000]
MAX_ATTEMPTS = 3


# === Tipos de resultado de un intento de descarga ===


class DownloadOutcome(Enum):
    """Posibles resultados de un intento de descarga individual."""

    SUCCESS = "success"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    HTTP_500 = "http_500"
    HTTP_502 = "http_502"
    HTTP_503 = "http_503"
    HTTP_429 = "http_429"  # Rate limit — se reintenta
    HTTP_400 = "http_400"  # Error de cliente — NO se reintenta
    HTTP_403 = "http_403"  # Forbidden — NO se reintenta
    HTTP_404 = "http_404"  # Not found — NO se reintenta


# Clasificación: ¿el error es 4xx (excepto 429)?
_CLIENT_ERRORS_NO_RETRY = {
    DownloadOutcome.HTTP_400,
    DownloadOutcome.HTTP_403,
    DownloadOutcome.HTTP_404,
}

# Errores que permiten reintento (5xx, 429, network, timeout)
_RETRYABLE_ERRORS = {
    DownloadOutcome.NETWORK_ERROR,
    DownloadOutcome.TIMEOUT,
    DownloadOutcome.HTTP_500,
    DownloadOutcome.HTTP_502,
    DownloadOutcome.HTTP_503,
    DownloadOutcome.HTTP_429,
}


# === Resultado de la simulación de retry ===


@dataclass
class RetryResult:
    """Resultado de simular el mecanismo de retry."""

    delays_used: list[int]  # Delays aplicados entre intentos (ms)
    total_attempts: int  # Total de intentos realizados
    succeeded: bool  # Si la descarga tuvo éxito
    stopped_early: bool  # Si se detuvo por error 4xx (sin reintentar)


# === Simulación de la lógica de retry (replica PushMessageHandler.DownloadWithRetryAsync) ===


def simulate_retry(failure_sequence: list[DownloadOutcome]) -> RetryResult:
    """
    Simula el mecanismo de retry con backoff exponencial del cliente C#.

    La lógica replica exactamente PushMessageHandler.DownloadWithRetryAsync:
    - Para cada intento, consume el siguiente resultado de failure_sequence
    - Si el resultado es SUCCESS: retorna inmediatamente (sin más intentos)
    - Si el resultado es un error 4xx (excepto 429): detiene sin reintentar
    - Si el resultado es retryable (5xx, 429, network, timeout): espera delay y reintenta
    - Si se agotan los intentos (MAX_ATTEMPTS): retorna fallo

    Args:
        failure_sequence: Lista de outcomes por intento. Si la lista es más corta
                         que MAX_ATTEMPTS, los intentos restantes se consideran como
                         errores de red (comportamiento conservador).

    Returns:
        RetryResult con delays_used, total_attempts, succeeded, stopped_early
    """
    delays_used: list[int] = []
    total_attempts = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        total_attempts = attempt

        # Obtener el outcome para este intento
        if attempt - 1 < len(failure_sequence):
            outcome = failure_sequence[attempt - 1]
        else:
            # Si la secuencia es más corta, asumir error de red
            outcome = DownloadOutcome.NETWORK_ERROR

        # Caso 1: Éxito — retornar inmediatamente sin más reintentos
        if outcome == DownloadOutcome.SUCCESS:
            return RetryResult(
                delays_used=delays_used,
                total_attempts=total_attempts,
                succeeded=True,
                stopped_early=False,
            )

        # Caso 2: Error 4xx (excepto 429) — detener sin reintentar
        if outcome in _CLIENT_ERRORS_NO_RETRY:
            return RetryResult(
                delays_used=delays_used,
                total_attempts=total_attempts,
                succeeded=False,
                stopped_early=True,
            )

        # Caso 3: Error retryable — aplicar delay si hay más intentos disponibles
        if attempt < MAX_ATTEMPTS:
            delay = DELAYS_MS[attempt - 1]
            delays_used.append(delay)

    # Todos los intentos agotados
    return RetryResult(
        delays_used=delays_used,
        total_attempts=total_attempts,
        succeeded=False,
        stopped_early=False,
    )


# === Estrategias de generación de datos ===

# Estrategia para generar un outcome retryable (5xx, 429, network, timeout)
_retryable_outcomes = st.sampled_from([
    DownloadOutcome.NETWORK_ERROR,
    DownloadOutcome.TIMEOUT,
    DownloadOutcome.HTTP_500,
    DownloadOutcome.HTTP_502,
    DownloadOutcome.HTTP_503,
    DownloadOutcome.HTTP_429,
])

# Estrategia para generar un error 4xx no-retryable
_client_error_outcomes = st.sampled_from([
    DownloadOutcome.HTTP_400,
    DownloadOutcome.HTTP_403,
    DownloadOutcome.HTTP_404,
])

# Estrategia para generar cualquier outcome (incluyendo success)
_any_outcome = st.sampled_from(list(DownloadOutcome))

# Secuencias de fallos seguidos de un posible éxito
_failure_sequences = st.lists(
    _any_outcome,
    min_size=1,
    max_size=MAX_ATTEMPTS,
)


# === PROPERTY TESTS ===


class TestExponentialBackoffRetry:
    """
    Property 6: Exponential backoff retry on S3 failure.

    Verifica las propiedades del mecanismo de retry con backoff exponencial
    para descargas desde S3 (configs y certificados):
    - Delays exactos [1000ms, 2000ms, 4000ms]
    - Máximo 3 intentos totales
    - Parada inmediata en errores 4xx (excepto 429)
    - Retorno inmediato en éxito

    Feature: push-based-distribution, Property 6: Exponential backoff retry on S3 failure

    **Validates: Requirements 2.5, 4.4**
    """

    @given(sequence=_failure_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_total_intentos_nunca_excede_max_attempts(
        self, sequence: list[DownloadOutcome]
    ):
        """
        Para cualquier secuencia de outcomes, el total de intentos
        nunca excede MAX_ATTEMPTS (3).

        **Validates: Requirements 2.5, 4.4**
        """
        result = simulate_retry(sequence)

        assert result.total_attempts <= MAX_ATTEMPTS, (
            f"Total de intentos ({result.total_attempts}) excede MAX_ATTEMPTS ({MAX_ATTEMPTS}). "
            f"Secuencia: {[o.value for o in sequence]}"
        )

    @given(sequence=_failure_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_delays_siguen_patron_exponencial_exacto(
        self, sequence: list[DownloadOutcome]
    ):
        """
        Para cualquier secuencia de fallos retryables, los delays entre
        reintentos siguen exactamente el patrón [1000ms, 2000ms, 4000ms].
        El delay en posición i es siempre DELAYS_MS[i].

        **Validates: Requirements 2.5, 4.4**
        """
        result = simulate_retry(sequence)

        # Cada delay usado debe coincidir con el patrón exponencial
        for i, delay in enumerate(result.delays_used):
            expected_delay = DELAYS_MS[i]
            assert delay == expected_delay, (
                f"Delay en posición {i} es {delay}ms, esperado {expected_delay}ms. "
                f"Patrón esperado: {DELAYS_MS[:len(result.delays_used)]}, "
                f"Obtenido: {result.delays_used}. "
                f"Secuencia: {[o.value for o in sequence]}"
            )

    @given(
        failures_before_success=st.integers(min_value=0, max_value=MAX_ATTEMPTS - 1),
        failure_types=st.lists(
            _retryable_outcomes,
            min_size=0,
            max_size=MAX_ATTEMPTS - 1,
        ),
    )
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_exito_en_cualquier_intento_retorna_inmediatamente(
        self, failures_before_success: int, failure_types: list[DownloadOutcome]
    ):
        """
        Si la descarga tiene éxito en el intento N (1 <= N <= 3),
        no se realizan intentos adicionales y el resultado es succeeded=True.

        **Validates: Requirements 2.5, 4.4**
        """
        # Construir secuencia: N-1 fallos retryables seguidos de SUCCESS
        actual_failures = failures_before_success
        # Asegurar que tenemos suficientes failure_types
        assume(len(failure_types) >= actual_failures)

        sequence = failure_types[:actual_failures] + [DownloadOutcome.SUCCESS]
        result = simulate_retry(sequence)

        assert result.succeeded is True, (
            f"Descarga debería tener éxito con secuencia que termina en SUCCESS. "
            f"Secuencia: {[o.value for o in sequence]}"
        )
        assert result.total_attempts == actual_failures + 1, (
            f"Total de intentos debería ser {actual_failures + 1} "
            f"({actual_failures} fallos + 1 éxito), obtenido {result.total_attempts}. "
            f"Secuencia: {[o.value for o in sequence]}"
        )
        # No debería haber intentos después del éxito
        assert len(result.delays_used) == actual_failures, (
            f"Debería haber {actual_failures} delays (uno por cada fallo antes del éxito), "
            f"obtenido {len(result.delays_used)}. "
            f"Secuencia: {[o.value for o in sequence]}"
        )

    @given(
        client_error=_client_error_outcomes,
        preceding_failures=st.lists(
            _retryable_outcomes,
            min_size=0,
            max_size=0,  # El error 4xx ocurre en el primer intento
        ),
    )
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_error_4xx_detiene_inmediatamente_sin_reintentar(
        self, client_error: DownloadOutcome, preceding_failures: list[DownloadOutcome]
    ):
        """
        En errores 4xx (excepto 429), el mecanismo se detiene inmediatamente
        sin reintentar. El total de intentos es 1 cuando el 4xx ocurre en el primer intento.

        **Validates: Requirements 2.5, 4.4**
        """
        # Error 4xx en el primer intento
        sequence = [client_error]
        result = simulate_retry(sequence)

        assert result.stopped_early is True, (
            f"Error 4xx ({client_error.value}) debería detener el retry inmediatamente. "
            f"stopped_early={result.stopped_early}"
        )
        assert result.total_attempts == 1, (
            f"Con error 4xx en primer intento, total_attempts debería ser 1, "
            f"obtenido {result.total_attempts}. Error: {client_error.value}"
        )
        assert result.succeeded is False, (
            f"Un error 4xx nunca produce succeeded=True. Error: {client_error.value}"
        )
        assert result.delays_used == [], (
            f"No debería haber delays cuando se detiene por error 4xx. "
            f"Delays: {result.delays_used}. Error: {client_error.value}"
        )

    @given(
        retryable_failures=st.lists(
            _retryable_outcomes,
            min_size=MAX_ATTEMPTS,
            max_size=MAX_ATTEMPTS,
        )
    )
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_todos_intentos_fallan_produce_fallo_final(
        self, retryable_failures: list[DownloadOutcome]
    ):
        """
        Si los 3 intentos fallan con errores retryables, el resultado es
        succeeded=False con exactly 2 delays y 3 intentos totales.

        **Validates: Requirements 2.5, 4.4**
        """
        result = simulate_retry(retryable_failures)

        assert result.succeeded is False, (
            f"Con 3 fallos consecutivos debería retornar succeeded=False. "
            f"Secuencia: {[o.value for o in retryable_failures]}"
        )
        assert result.total_attempts == MAX_ATTEMPTS, (
            f"Con 3 fallos retryables debería hacer {MAX_ATTEMPTS} intentos, "
            f"obtenido {result.total_attempts}. "
            f"Secuencia: {[o.value for o in retryable_failures]}"
        )
        assert result.stopped_early is False, (
            f"No debería marcar stopped_early con errores retryables. "
            f"Secuencia: {[o.value for o in retryable_failures]}"
        )
        # Debe haber exactamente 2 delays (entre intento 1→2 y 2→3)
        assert len(result.delays_used) == MAX_ATTEMPTS - 1, (
            f"Debería haber {MAX_ATTEMPTS - 1} delays entre los 3 intentos, "
            f"obtenido {len(result.delays_used)}. Delays: {result.delays_used}"
        )
        # Verificar delays exactos
        assert result.delays_used == DELAYS_MS[:MAX_ATTEMPTS - 1], (
            f"Delays deberían ser {DELAYS_MS[:MAX_ATTEMPTS - 1]}, "
            f"obtenido {result.delays_used}"
        )

    @given(
        preceding_retryable=st.lists(
            _retryable_outcomes,
            min_size=1,
            max_size=MAX_ATTEMPTS - 1,
        ),
        client_error=_client_error_outcomes,
    )
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_error_4xx_despues_de_fallos_retryables_detiene(
        self,
        preceding_retryable: list[DownloadOutcome],
        client_error: DownloadOutcome,
    ):
        """
        Si hay fallos retryables seguidos de un error 4xx, el mecanismo se detiene
        en el intento del 4xx sin más reintentos.

        **Validates: Requirements 2.5, 4.4**
        """
        # Limitar para no exceder MAX_ATTEMPTS
        assume(len(preceding_retryable) + 1 <= MAX_ATTEMPTS)

        sequence = preceding_retryable + [client_error]
        result = simulate_retry(sequence)

        expected_attempts = len(preceding_retryable) + 1
        assert result.total_attempts == expected_attempts, (
            f"Debería hacer {expected_attempts} intentos "
            f"({len(preceding_retryable)} retryables + 1 client_error), "
            f"obtenido {result.total_attempts}. "
            f"Secuencia: {[o.value for o in sequence]}"
        )
        assert result.stopped_early is True, (
            f"Debería marcar stopped_early por error 4xx. "
            f"Secuencia: {[o.value for o in sequence]}"
        )
        assert result.succeeded is False, (
            f"No debería tener éxito con error 4xx. "
            f"Secuencia: {[o.value for o in sequence]}"
        )

    @given(sequence=_failure_sequences)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_delays_usados_es_uno_menos_que_intentos_retryables(
        self, sequence: list[DownloadOutcome]
    ):
        """
        El número de delays usados es siempre: (intentos con fallo retryable) - 1
        si el último intento también falla, o igual al número de fallos retryables
        si el siguiente intento es éxito o client_error.

        Más precisamente: delays_used tiene un elemento por cada transición
        entre un fallo retryable y el siguiente intento.

        **Validates: Requirements 2.5, 4.4**
        """
        result = simulate_retry(sequence)

        # Contar cuántos fallos retryables precedieron al resultado final
        retryable_count = 0
        for i in range(result.total_attempts):
            if i < len(sequence):
                outcome = sequence[i]
            else:
                outcome = DownloadOutcome.NETWORK_ERROR

            if outcome == DownloadOutcome.SUCCESS:
                break
            if outcome in _CLIENT_ERRORS_NO_RETRY:
                break
            retryable_count += 1

        # Los delays son entre intentos retryables y el siguiente intento
        # Si hubo N fallos retryables y un intento más (éxito, 4xx, o último fallo),
        # los delays son N si hay siguiente intento, o N-1 si no hay más intentos
        if result.total_attempts < MAX_ATTEMPTS or result.succeeded or result.stopped_early:
            # El último fallo retryable fue seguido de otro intento → delays = retryable_count
            # Pero si el resultado final es por agotar intentos, el último no tiene delay
            expected_delays = retryable_count
            if not result.succeeded and not result.stopped_early:
                # Todos los intentos fallaron → delays entre ellos (N-1)
                expected_delays = result.total_attempts - 1
        else:
            expected_delays = result.total_attempts - 1

        assert len(result.delays_used) == expected_delays, (
            f"Cantidad de delays incorrecta. Esperado: {expected_delays}, "
            f"Obtenido: {len(result.delays_used)}. "
            f"total_attempts={result.total_attempts}, succeeded={result.succeeded}, "
            f"stopped_early={result.stopped_early}, retryable_count={retryable_count}. "
            f"Secuencia: {[o.value for o in sequence[:result.total_attempts]]}"
        )

    @given(
        failure_type=_retryable_outcomes,
    )
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_http_429_se_reintenta_como_error_servidor(
        self, failure_type: DownloadOutcome
    ):
        """
        El código 429 (Too Many Requests) se trata como error retryable,
        no como error de cliente 4xx. Esto es una excepción explícita.

        **Validates: Requirements 2.5, 4.4**
        """
        # Secuencia con solo 429 seguido de éxito
        sequence = [DownloadOutcome.HTTP_429, DownloadOutcome.SUCCESS]
        result = simulate_retry(sequence)

        assert result.succeeded is True, (
            "HTTP 429 debería ser retryable — el siguiente intento debería ejecutarse. "
            f"Resultado: succeeded={result.succeeded}, stopped_early={result.stopped_early}"
        )
        assert result.total_attempts == 2, (
            f"Debería hacer 2 intentos (429 + éxito), obtenido {result.total_attempts}"
        )
        assert result.stopped_early is False, (
            "HTTP 429 NO debería causar stopped_early (es retryable, no client error)"
        )
