namespace AlwaysPrint.Shared.Messages
{
    /// <summary>
    /// Constantes compartidas del protocolo Named Pipe.
    /// Centralizadas aquí para que tanto el servicio como el Tray usen el mismo valor
    /// sin crear una dependencia cruzada entre proyectos.
    /// </summary>
    public static class PipeConstants
    {
        /// <summary>Nombre del Named Pipe: \\.\pipe\AlwaysPrintService</summary>
        public const string PipeName = "AlwaysPrintService";
    }
}
