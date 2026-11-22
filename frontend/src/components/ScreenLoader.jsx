// Full-screen fallback used while a lazily loaded page chunk downloads. Pages
// rendered inside AppLayout use LoadingState instead, so the shell stays visible;
// this one is for routes that render standalone (login, register, reset).
export default function ScreenLoader() {
  return (
    <div className="grid min-h-screen place-items-center bg-[#EEF1F5] dark:bg-[#0A0A0A]" role="status" aria-label="Loading">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#E4E8EE] dark:border-[#252A30] border-t-[#007BA7]" />
    </div>
  );
}
