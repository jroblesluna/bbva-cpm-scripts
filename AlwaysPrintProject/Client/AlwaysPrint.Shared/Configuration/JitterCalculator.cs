using System;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Calcula el delay de jitter para reconexiones y arranques,
    /// distribuyendo las conexiones uniformemente dentro de la ventana configurada.
    /// Previene el efecto "thundering herd" cuando múltiples workstations
    /// intentan reconectarse simultáneamente.
    /// </summary>
    public static class JitterCalculator
    {
        /// <summary>
        /// Valor por defecto de la ventana de jitter en segundos.
        /// Se usa cuando el valor configurado es inválido o ausente.
        /// </summary>
        private const int DefaultJitterWindowSeconds = 30;

        /// <summary>
        /// Valor mínimo permitido para la ventana de jitter (segundos).
        /// </summary>
        private const int MinJitterWindow = 5;

        /// <summary>
        /// Valor máximo permitido para la ventana de jitter (segundos).
        /// </summary>
        private const int MaxJitterWindow = 300;

        /// <summary>
        /// Umbral en segundos para considerar un timestamp como "reciente".
        /// Si la diferencia entre utcNow y el timestamp es menor a este valor,
        /// se considera que el evento fue causado por una acción masiva.
        /// </summary>
        private const int RecentThresholdSeconds = 60;

        /// <summary>
        /// Calcula el delay en milisegundos antes de conectar al WebSocket durante el arranque.
        /// Retorna 0 si no se requiere jitter (timestamp ausente, inválido, futuro o antiguo).
        /// Si ambos timestamps son recientes, usa el más cercano a utcNow y aplica jitter una sola vez.
        /// </summary>
        /// <param name="utcNow">Momento actual en UTC.</param>
        /// <param name="lastUpdateTimestamp">Timestamp de la última actualización MSI (null si ausente o inválido).</param>
        /// <param name="lastRestartTimestamp">Timestamp del último reinicio de Tray (null si ausente o inválido).</param>
        /// <param name="jitterWindowSeconds">Ventana de jitter en segundos leída del Registry.</param>
        /// <param name="rng">Generador aleatorio opcional para testing determinístico.</param>
        /// <returns>Tupla con el delay en milisegundos y la razón del jitter (null si no aplica).</returns>
        public static (int delayMs, string? reason) ComputeStartupDelay(
            DateTime utcNow,
            DateTime? lastUpdateTimestamp,
            DateTime? lastRestartTimestamp,
            int jitterWindowSeconds,
            Random? rng = null)
        {
            // Normalizar la ventana de jitter al rango válido
            int normalizedWindow = NormalizeJitterWindow(jitterWindowSeconds);

            // Evaluar si el timestamp de actualización es reciente y válido
            bool updateIsRecent = IsTimestampRecent(utcNow, lastUpdateTimestamp);
            // Evaluar si el timestamp de reinicio es reciente y válido
            bool restartIsRecent = IsTimestampRecent(utcNow, lastRestartTimestamp);

            // Si ningún timestamp es reciente, no aplicar jitter
            if (!updateIsRecent && !restartIsRecent)
            {
                return (0, null);
            }

            string reason;

            if (updateIsRecent && restartIsRecent)
            {
                // Ambos son recientes: usar el más cercano a utcNow (menor diferencia)
                double updateDiff = (utcNow - lastUpdateTimestamp!.Value).TotalSeconds;
                double restartDiff = (utcNow - lastRestartTimestamp!.Value).TotalSeconds;

                // El más cercano tiene menor diferencia temporal
                reason = restartDiff <= updateDiff ? "post-restart" : "post-update";
            }
            else if (updateIsRecent)
            {
                reason = "post-update";
            }
            else
            {
                reason = "post-restart";
            }

            // Calcular delay aleatorio uniforme en [0, normalizedWindow * 1000) ms
            Random random = rng ?? new Random();
            int delayMs = random.Next(0, normalizedWindow * 1000);

            return (delayMs, reason);
        }

        /// <summary>
        /// Calcula el delay para el primer intento de reconexión tras una desconexión WebSocket.
        /// Siempre aplica jitter con distribución uniforme U(0, W*1000).
        /// </summary>
        /// <param name="jitterWindowSeconds">Ventana de jitter en segundos leída del Registry.</param>
        /// <param name="rng">Generador aleatorio opcional para testing determinístico.</param>
        /// <returns>Delay en milisegundos para el primer intento de reconexión.</returns>
        public static int ComputeReconnectionDelay(int jitterWindowSeconds, Random? rng = null)
        {
            // Normalizar la ventana de jitter al rango válido
            int normalizedWindow = NormalizeJitterWindow(jitterWindowSeconds);

            // Calcular delay aleatorio uniforme en [0, normalizedWindow * 1000) ms
            Random random = rng ?? new Random();
            return random.Next(0, normalizedWindow * 1000);
        }

        /// <summary>
        /// Normaliza el valor de la ventana de jitter.
        /// Si está fuera del rango [5, 300], retorna el valor por defecto (30).
        /// </summary>
        /// <param name="rawValue">Valor crudo leído del Registry o configuración.</param>
        /// <returns>Valor normalizado dentro del rango válido, o 30 si es inválido.</returns>
        public static int NormalizeJitterWindow(int rawValue)
        {
            if (rawValue < MinJitterWindow || rawValue > MaxJitterWindow)
            {
                return DefaultJitterWindowSeconds;
            }
            return rawValue;
        }

        /// <summary>
        /// Determina si un timestamp es "reciente" (< 60 segundos de antigüedad).
        /// Un timestamp es considerado NO reciente si:
        /// - Es null (ausente)
        /// - Es futuro respecto a utcNow (inválido)
        /// - Tiene 60 o más segundos de antigüedad
        /// </summary>
        /// <param name="utcNow">Momento actual en UTC.</param>
        /// <param name="timestamp">Timestamp a evaluar (null si ausente o inválido).</param>
        /// <returns>True si el timestamp es válido y reciente (< 60s).</returns>
        private static bool IsTimestampRecent(DateTime utcNow, DateTime? timestamp)
        {
            // Timestamp ausente → no es reciente
            if (!timestamp.HasValue)
            {
                return false;
            }

            // Timestamp futuro → inválido, tratar como ausente
            if (timestamp.Value > utcNow)
            {
                return false;
            }

            // Calcular diferencia en segundos
            double diffSeconds = (utcNow - timestamp.Value).TotalSeconds;

            // Reciente solo si la diferencia es menor al umbral (60s)
            return diffSeconds < RecentThresholdSeconds;
        }
    }
}
