export default function LoadingState() {
  return (
    <div className="space-y-3 clarivo-panel p-6">
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="flex animate-pulse items-center gap-4">
          <div className="h-10 w-10 rounded-[14px] bg-[#F5F7FA] dark:bg-[#171A1D] border border-[#E4E8EE] dark:border-[#252A30]" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-1/3 rounded-full bg-[#F5F7FA] dark:bg-[#171A1D]" />
            <div className="h-3 w-2/3 rounded-full bg-[#F5F7FA] dark:bg-[#171A1D]" />
          </div>
          <div className="h-8 w-20 rounded-full bg-[#F5F7FA] dark:bg-[#171A1D]" />
        </div>
      ))}
    </div>
  );
}
