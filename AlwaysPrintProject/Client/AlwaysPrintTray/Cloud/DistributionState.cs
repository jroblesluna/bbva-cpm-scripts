using System;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Estado de distribución recibido del servidor vía WebSocket.
    /// Contiene los hashes/versiones actuales que la workstation debería tener.
    /// Se actualiza al recibir Registration_Enrichment o push messages individuales.
    /// </summary>
    public class DistributionState
    {
        /// <summary>Hash SHA256 corto (8 chars) de la configuración de acciones activa.</summary>
        public string ConfigHash { get; set; }

        /// <summary>URL pública de S3 del archivo de configuración firmado (.signed).</summary>
        public string ConfigS3Url { get; set; }

        /// <summary>Versión del certificado ECDSA de la organización (0 = sin certificado).</summary>
        public int CertVersion { get; set; }

        /// <summary>URL pública de S3 del certificado ECDSA (.cer).</summary>
        public string CertUrl { get; set; }

        /// <summary>Versión target del MSI de la organización.</summary>
        public string MsiVersion { get; set; }

        /// <summary>Presigned URL de S3 para descarga directa del MSI.</summary>
        public string MsiUrl { get; set; }

        /// <summary>Tamaño del archivo MSI en bytes (0 = desconocido).</summary>
        public long MsiFileSize { get; set; }

        /// <summary>Fecha/hora UTC de la última actualización de este estado.</summary>
        public DateTime LastUpdated { get; set; }
    }
}
