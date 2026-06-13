namespace AlwaysPrintTray.OnDemand
{
    /// <summary>
    /// DTO liviano con la información necesaria para la UI.
    /// Representa un trigger OnDemand disponible para el usuario.
    /// </summary>
    public class OnDemandTriggerInfo
    {
        /// <summary>Etiqueta visible en la UI e identificador único del trigger.</summary>
        public string Label { get; set; } = string.Empty;

        /// <summary>Descripción mostrada en el diálogo de confirmación antes de ejecutar.</summary>
        public string Description { get; set; } = string.Empty;
    }
}
