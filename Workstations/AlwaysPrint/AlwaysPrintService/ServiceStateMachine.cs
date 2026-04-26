using System;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Models;

namespace AlwaysPrintService
{
    /// <summary>
    /// Manages the service lifecycle state.
    /// Thread-safe: state writes are serialized through a lock;
    /// reads are cheap volatile reads for observability.
    /// </summary>
    public sealed class ServiceStateMachine
    {
        private volatile ServiceState _current = ServiceState.Starting;
        private readonly object _lock = new object();

        public ServiceState Current => _current;

        public event Action<ServiceState, ServiceState>? StateChanged;

        public void Transition(ServiceState next)
        {
            ServiceState prev;
            lock (_lock)
            {
                if (_current == next) return;
                prev = _current;
                _current = next;
            }

            AlwaysPrintLogger.WriteInfo(
                $"ServiceState: {prev} → {next}",
                AlwaysPrintLogger.EvtServiceStarted);

            StateChanged?.Invoke(prev, next);
        }

        public bool Is(ServiceState state) => _current == state;
    }
}
