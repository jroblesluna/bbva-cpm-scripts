using System;
using System.Net;
using System.Net.Http;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Detecta y configura el proxy corporativo para las conexiones HTTP/WebSocket del Tray.
    /// Usa el proxy del sistema (configurado en IE/WinInet) como primera opción.
    /// </summary>
    public static class ProxyHelper
    {
        /// <summary>
        /// Retorna un HttpClientHandler configurado con el proxy del sistema si existe.
        /// El handler usa CredentialCache.DefaultCredentials para autenticación NTLM/Kerberos.
        /// </summary>
        public static HttpClientHandler CreateHandler()
        {
            var handler = new HttpClientHandler
            {
                UseProxy = true,
                Proxy    = WebRequest.GetSystemWebProxy()
            };
            handler.Proxy.Credentials = CredentialCache.DefaultCredentials;

            AlwaysPrintLogger.WriteTrayInfo("ProxyHelper: handler HTTP creado con proxy del sistema.");
            return handler;
        }

        /// <summary>
        /// Retorna la URI del proxy del sistema para la URI destino dada,
        /// o null si el destino está en la lista de bypass del proxy.
        /// </summary>
        /// <param name="targetUri">URI destino para la cual se busca el proxy.</param>
        /// <returns>URI del proxy, o null si el destino es directo (bypass).</returns>
        public static Uri GetSystemProxyUri(Uri targetUri)
        {
            var proxy = WebRequest.GetSystemWebProxy();

            if (proxy.IsBypassed(targetUri))
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ProxyHelper: destino {targetUri.Host} está en bypass del proxy.");
                return null;
            }

            var proxyUri = proxy.GetProxy(targetUri);
            if (proxyUri != null && proxyUri != targetUri)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ProxyHelper: proxy detectado para {targetUri.Host} -> {proxyUri}");
                return proxyUri;
            }

            return null;
        }
    }
}
