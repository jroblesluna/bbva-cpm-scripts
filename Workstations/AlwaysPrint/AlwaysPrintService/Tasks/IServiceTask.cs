namespace AlwaysPrintService.Tasks
{
    public interface IServiceTask
    {
        ServiceTaskResult Execute();
    }

    public sealed class ServiceTaskResult
    {
        public bool    Success { get; }
        public string  Message { get; }
        public object? Data    { get; }

        public ServiceTaskResult(bool success, string message, object? data = null)
        {
            Success = success;
            Message = message;
            Data    = data;
        }

        public static ServiceTaskResult Ok(string message = "OK", object? data = null)
            => new ServiceTaskResult(true,  message, data);

        public static ServiceTaskResult Fail(string message, object? data = null)
            => new ServiceTaskResult(false, message, data);
    }
}
