using System;
using System.IO;

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

        /// <summary>
        /// Directorio base para archivos de configuración de acciones.
        /// Ruta: C:\ProgramData\AlwaysPrint\config\
        /// El Service (LocalSystem) escribe aquí; el Tray (usuario normal) solo lee.
        /// </summary>
        public static string ActionConfigDirectory => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "AlwaysPrint", "config");

        /// <summary>
        /// Ruta completa del archivo de configuración de acciones activa.
        /// Ruta: C:\ProgramData\AlwaysPrint\config\active.alwaysconfig
        /// </summary>
        public static string ActionConfigFilePath => Path.Combine(ActionConfigDirectory, "active.alwaysconfig");
    }
}
