using System;
using System.Collections.Concurrent;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using AlwaysPrintService.Tasks;

namespace AlwaysPrintService.Queue
{
    /// <summary>
    /// Thread-safe producer/consumer task queue.
    ///
    /// Design choice: BlockingCollection over Channel<T> because we target .NET Framework 4.8
    /// and want zero additional NuGet dependencies for this core component. BlockingCollection
    /// provides bounded capacity (prevents unbounded memory growth if tasks pile up), blocking
    /// Take for the consumer thread, and safe cancellation via CancellationToken.
    /// </summary>
    public sealed class TaskQueueManager : IDisposable
    {
        private const int MaxQueueCapacity = 256;

        private readonly BlockingCollection<IServiceTask> _queue =
            new BlockingCollection<IServiceTask>(new ConcurrentQueue<IServiceTask>(), MaxQueueCapacity);

        private readonly CancellationTokenSource _cts = new CancellationTokenSource();
        private Thread? _workerThread;
        private bool _disposed;

        public int PendingCount => _queue.Count;

        public void Start()
        {
            _workerThread = new Thread(WorkerLoop)
            {
                IsBackground = true,
                Name = "AlwaysPrint-TaskWorker"
            };
            _workerThread.Start();
            EventLogWriter.WriteInfo("TaskQueueManager started.", EventLogWriter.EvtServiceStarted);
        }

        /// <summary>
        /// Enqueues a task. Returns false if the queue is full (task is dropped with a warning).
        /// </summary>
        public bool Enqueue(IServiceTask task)
        {
            if (task == null) throw new ArgumentNullException(nameof(task));
            if (_queue.IsAddingCompleted) return false;

            bool accepted = _queue.TryAdd(task, millisecondsTimeout: 0);
            if (!accepted)
                EventLogWriter.WriteWarning(
                    $"TaskQueueManager: queue full ({MaxQueueCapacity}), task '{task.GetType().Name}' dropped.",
                    EventLogWriter.EvtGenericWarning);
            else
                EventLogWriter.WriteInfo(
                    $"TaskQueueManager: enqueued '{task.GetType().Name}'. Pending={_queue.Count}",
                    EventLogWriter.EvtTaskDispatched);

            return accepted;
        }

        /// <summary>Drains and discards all pending tasks. Returns the count removed.</summary>
        public int ClearAll()
        {
            int removed = 0;
            while (_queue.TryTake(out _)) removed++;
            return removed;
        }

        private void WorkerLoop()
        {
            EventLogWriter.WriteInfo("TaskQueueManager worker loop started.");
            try
            {
                foreach (var task in _queue.GetConsumingEnumerable(_cts.Token))
                {
                    try
                    {
                        EventLogWriter.WriteInfo(
                            $"TaskQueueManager: executing '{task.GetType().Name}'.",
                            EventLogWriter.EvtTaskDispatched);

                        var result = task.Execute();

                        if (result.Success)
                            EventLogWriter.WriteInfo(
                                $"TaskQueueManager: '{task.GetType().Name}' completed. {result.Message}",
                                EventLogWriter.EvtTaskCompleted);
                        else
                            EventLogWriter.WriteWarning(
                                $"TaskQueueManager: '{task.GetType().Name}' failed. {result.Message}",
                                EventLogWriter.EvtTaskFailed);
                    }
                    catch (Exception ex)
                    {
                        EventLogWriter.WriteError(
                            $"TaskQueueManager: unhandled exception in '{task.GetType().Name}'.", ex,
                            EventLogWriter.EvtTaskFailed);
                    }
                }
            }
            catch (OperationCanceledException)
            {
                // Normal shutdown.
            }
            EventLogWriter.WriteInfo("TaskQueueManager worker loop ended.");
        }

        public void Stop()
        {
            _queue.CompleteAdding();
            _cts.Cancel();
            _workerThread?.Join(TimeSpan.FromSeconds(10));
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Stop();
            _queue.Dispose();
            _cts.Dispose();
        }
    }
}
