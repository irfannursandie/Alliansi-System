import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";

export default function PoolDashboard() {
  const { API } = useAuth();

  const [activeDrivers, setActiveDrivers] = useState([]);
  const [absentDrivers, setAbsentDrivers] = useState([]);
  const [unknownDrivers, setUnknownDrivers] = useState([]);
  const [time, setTime] = useState(new Date().toLocaleTimeString("id-ID"));

  const activeListRef = useRef(null);
  const absentListRef = useRef(null);
  const unknownListRef = useRef(null);

  // Auto-scroll function
  const setupAutoScroll = (containerRef) => {
    if (!containerRef?.current) return;
    const container = containerRef.current;
    const scrollSpeed = 1;
    const scrollInterval = setInterval(() => {
      container.scrollTop += scrollSpeed;
      if (container.scrollTop >= container.scrollHeight - container.clientHeight) {
        container.scrollTop = 0;
      }
    }, 50);
    return scrollInterval;
  };

  useEffect(() => {
    let mounted = true;
    let scrollIntervals = [];

    const fetchData = () => {
      axios.get(`${API}/pool-dashboard`)
        .then(res => {
          if (!mounted) return;
          setActiveDrivers(res.data.active || []);
          setAbsentDrivers(res.data.absent || []);
          setUnknownDrivers(res.data.unknown || []);
        })
        .catch(() => {});
    };

    fetchData();
    const clockInterval = setInterval(() => {
      setTime(new Date().toLocaleTimeString("id-ID"));
    }, 1000);
    const dataInterval = setInterval(fetchData, 30000);
    
    return () => {
      mounted = false;
      clearInterval(clockInterval);
      clearInterval(dataInterval);
      scrollIntervals.forEach(interval => clearInterval(interval));
    };
  }, [API]);

  // Auto-scroll setup - runs after data loads
  useEffect(() => {
    let scrollIntervals = [];
    
    const activeScroll = setupAutoScroll(activeListRef);
    const absentScroll = setupAutoScroll(absentListRef);
    const unknownScroll = setupAutoScroll(unknownListRef);
    
    if (activeScroll) scrollIntervals.push(activeScroll);
    if (absentScroll) scrollIntervals.push(absentScroll);
    if (unknownScroll) scrollIntervals.push(unknownScroll);

    return () => {
      scrollIntervals.forEach(interval => clearInterval(interval));
    };
  }, [activeDrivers, absentDrivers, unknownDrivers]);

  return (
    <div className="h-screen bg-zinc-950 text-white flex flex-col font-sans overflow-hidden">
      <div className="flex justify-between items-center p-6 bg-zinc-900 border-b-2 border-zinc-800">
        <div>
          <h1 className="text-3xl font-black text-emerald-400 tracking-wider">
            ALLIANSI SMF — COMMAND CENTER
          </h1>
          <p className="text-zinc-400 text-lg mt-1">Status Kehadiran Mitra</p>
        </div>
        <div className="text-right">
          <h2 className="text-5xl font-mono font-bold text-sky-400 tracking-tighter">
            {time}
          </h2>
          <p className="text-zinc-400 text-lg mt-1">
            {new Date().toLocaleDateString("id-ID", {
              weekday: "long",
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 p-6 flex-1 overflow-hidden">
        <div className="bg-zinc-900 rounded-xl border-t-4 border-emerald-500 p-4 shadow-lg overflow-hidden">
          <h3 className="text-xl font-bold text-emerald-400 mb-4 flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse"></span>
            ON-DUTY (HADIR)
          </h3>
          <div ref={activeListRef} className="h-full overflow-y-auto scrollbar-hide space-y-3" style={{scrollbarWidth: 'none', msOverflowStyle: 'none'}}>
            {activeDrivers.map((d, idx) => (
              <div
                key={idx}
                className="flex justify-between items-center bg-zinc-800/50 p-3 rounded-lg border border-zinc-700"
              >
                <div>
                  <p className="font-bold text-lg text-white">{d.name}</p>
                  <p className="text-zinc-400 text-sm">{d.plate}</p>
                </div>
                <div className="text-right">
                  <p className="text-emerald-400 font-mono font-bold">
                    {d.time}
                  </p>
                  <p className="text-xs text-zinc-500">Input SIJ</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-zinc-900 rounded-xl border-t-4 border-zinc-500 p-4 shadow-lg overflow-hidden">
          <h3 className="text-xl font-bold text-zinc-300 mb-4">
            KONFIRMASI TIDAK HADIR
          </h3>
          <div ref={absentListRef} className="h-full overflow-y-auto scrollbar-hide space-y-3" style={{scrollbarWidth: 'none', msOverflowStyle: 'none'}}>
            {absentDrivers.map((d, idx) => (
              <div
                key={idx}
                className="flex justify-between items-center bg-zinc-800/30 p-3 rounded-lg border border-zinc-800 opacity-70"
              >
                <p className="font-bold text-lg text-zinc-300">{d.name}</p>
                <span className="px-3 py-1 bg-zinc-700 rounded-full text-xs font-bold text-zinc-300">
                  {d.reason}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-zinc-900 rounded-xl border-t-4 border-rose-500 p-4 shadow-lg overflow-hidden">
          <h3 className="text-xl font-bold text-rose-400 mb-4 flex items-center gap-2">
            BELUM HADIR
          </h3>
          <div ref={unknownListRef} className="h-full overflow-y-auto scrollbar-hide space-y-3" style={{scrollbarWidth: 'none', msOverflowStyle: 'none'}}>
            {unknownDrivers.map((d, idx) => (
              <div
                key={idx}
                className="flex justify-between items-center bg-rose-500/10 p-3 rounded-lg border border-rose-500/20"
              >
                <div>
                  <p className="font-bold text-lg text-rose-200">{d.name}</p>
                  <p className="text-rose-400/60 text-sm">{d.plate}</p>
                </div>
                <span className="px-3 py-1 bg-rose-500/20 rounded-full text-xs font-bold text-rose-400">
                  Cek Keberadaan
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes marquee {
          0% { transform: translateX(100%); }
          100% { transform: translateX(-100%); }
        }
        .marquee-text {
          animation: marquee 45s linear infinite;
          display: inline-block;
        }
        .scrollbar-hide::-webkit-scrollbar {
          display: none;
        }
      `}</style>
      <div className="bg-emerald-500 p-3 text-zinc-950 font-bold text-center text-xl overflow-hidden whitespace-nowrap">
        <span className="marquee-text">
          INFO: Tetap utamakan keselamatan kerja | Cek kondisi unit sebelum berangkat | Selalu gunakan seragam yang rapi selama beroperasi. &nbsp;&nbsp;&nbsp;&nbsp; INFO: Tetap utamakan keselamatan kerja | Cek kondisi unit sebelum berangkat | Selalu gunakan seragam yang rapi selama beroperasi.
        </span>
      </div>
    </div>
  );
}
