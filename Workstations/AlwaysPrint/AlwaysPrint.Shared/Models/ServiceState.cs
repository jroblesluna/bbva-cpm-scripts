namespace AlwaysPrint.Shared.Models
{
    public enum ServiceState
    {
        Starting,
        WaitingUser,
        TrayStarting,
        TrayStarted,
        Running,
        TrayError,
        Stopping,
        Stopped
    }
}
