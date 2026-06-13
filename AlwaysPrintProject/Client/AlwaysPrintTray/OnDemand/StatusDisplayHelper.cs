namespace AlwaysPrintTray.OnDemand
{
    /// <summary>
    /// Métodos auxiliares para generar textos de display en el StatusForm.
    /// Separados como funciones puras para facilitar testing.
    /// </summary>
    public static class StatusDisplayHelper
    {
        /// <summary>
        /// Genera el texto de display de la configuración activa.
        /// Formato: "{name} v{version}"
        /// </summary>
        /// <param name="name">Nombre de la configuración activa.</param>
        /// <param name="version">Versión de la configuración activa.</param>
        /// <returns>Texto formateado para mostrar en la UI.</returns>
        public static string FormatConfigDisplay(string name, string version)
        {
            return $"{name} v{version}";
        }

        /// <summary>
        /// Determina el texto de display del estado del sistema basándose
        /// en el valor de ContingencyEnabled.
        /// </summary>
        /// <param name="contingencyEnabled">true si la contingencia está activa.</param>
        /// <returns>"En Contingencia" si está activo, "Normal" en caso contrario.</returns>
        public static string FormatEstadoSistema(bool contingencyEnabled)
        {
            return contingencyEnabled
                ? AlwaysPrintTray.Localization.LocalizationManager.Get("StatusStateContingency")
                : AlwaysPrintTray.Localization.LocalizationManager.Get("StatusStateNormal");
        }

        /// <summary>
        /// Genera el texto de display de la cola activa gestionada.
        /// - Modo CPM (sin remote_queue_path): solo el nombre de la cola.
        /// - Modo LPM (con remote_queue_path): "nombre (ruta_remota)".
        /// </summary>
        /// <param name="queueName">Nombre de la cola corporativa (ej: "LexmarkBBVA").</param>
        /// <param name="remoteQueuePath">Ruta remota de la cola LPM, o null/vacío si es modo CPM.</param>
        /// <returns>Texto formateado para mostrar en la UI.</returns>
        public static string FormatColaActiva(string queueName, string? remoteQueuePath)
        {
            if (!string.IsNullOrWhiteSpace(remoteQueuePath))
            {
                return $"{queueName} ({remoteQueuePath})";
            }

            return queueName;
        }
    }
}
