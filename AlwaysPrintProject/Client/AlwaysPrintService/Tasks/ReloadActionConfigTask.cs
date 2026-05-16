using System;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Tasks
{
    /// <summary>
    /// Tarea que recarga la configuración de acciones y ejecuta el trigger OnConfigChange.
    /// Se ejecuta cuando el Tray notifica que hay una nueva configuración disponible.
    /// </summary>
    public sealed class ReloadActionConfigTask : IServiceTask
    {
        private readonly Action _reloadCallback;

        /// <summary>
        /// Constructor que recibe un callback para recargar la configuración.
        /// </summary>
        /// <param name="reloadCallback">Acción que ejecuta la recarga (típicamente AlwaysPrintWindowsService.ReloadActionConfiguration)</param>
        public ReloadActionConfigTask(Action reloadCallback)
        {
            _reloadCallback = reloadCallback ?? throw new ArgumentNullException(nameof(reloadCallback));
        }

        public ServiceTaskResult Execute()
        {
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    "ReloadActionConfigTask: iniciando recarga de configuración de acciones",
                    AlwaysPrintLogger.EvtConfigSaved);
                
                // Ejecutar callback para recargar configuración
                _reloadCallback();
                
                AlwaysPrintLogger.WriteInfo(
                    "ReloadActionConfigTask: configuración recargada exitosamente",
                    AlwaysPrintLogger.EvtConfigSaved);
                
                return ServiceTaskResult.Ok("Configuración de acciones recargada.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ReloadActionConfigTask: error recargando configuración: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return ServiceTaskResult.Fail($"Error: {ex.Message}");
            }
        }
    }
}
