namespace AlwaysPrintTray.Connectivity
{
    /// <summary>
    /// Modelo que almacena el resultado de verificar la conectividad de una URL individual.
    /// </summary>
    public class UrlCheckResult
    {
        /// <summary>
        /// URL verificada.
        /// </summary>
        public string Url { get; set; }

        /// <summary>
        /// Indica si la URL fue accesible (cualquier respuesta HTTP = OK).
        /// Solo excepciones de transporte (DNS, TCP, TLS, timeout) = FALLO.
        /// </summary>
        public bool Success { get; set; }

        /// <summary>
        /// Latencia de la última solicitud en milisegundos.
        /// </summary>
        public long LatencyMs { get; set; }

        /// <summary>
        /// Código de estado HTTP de la última respuesta (0 si no hubo respuesta).
        /// </summary>
        public int StatusCode { get; set; }

        /// <summary>
        /// Número total de intentos realizados (1 = sin reintentos).
        /// </summary>
        public int Attempts { get; set; }

        /// <summary>
        /// Mensaje de error si la verificación falló; null si fue exitosa.
        /// </summary>
        public string Error { get; set; }

        /// <summary>true si la URL es crítica para el semáforo de notificación.</summary>
        public bool Critical { get; set; }

        /// <summary>Función descriptiva de la URL (para el reporte).</summary>
        public string Function { get; set; }
    }
}
