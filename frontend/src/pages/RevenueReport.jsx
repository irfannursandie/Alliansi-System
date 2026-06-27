import { useState, useEffect } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { TrendingUp, Download, FileDown } from "lucide-react";

const formatRp = (v) => "Rp " + new Intl.NumberFormat("id-ID").format(v);

const PERIODS = [
  { key: "daily", label: "Harian" },
  { key: "weekly", label: "Mingguan" },
  { key: "monthly", label: "Bulanan" },
];

const todayISO = () => new Date().toISOString().split("T")[0];

export default function RevenueReport() {
  const { getAuthHeader, API } = useAuth();
  const [period, setPeriod] = useState("monthly");
  const [date, setDate] = useState(todayISO());
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const fetchReport = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/revenue-report`, {
        params: { period, date },
        headers: getAuthHeader(),
      });
      setRows(res.data.rows || []);
      setMeta(res.data.meta);
    } catch {
      toast.error("Gagal memuat Revenue Report");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchReport();
  }, [period, date]);

  const handleExport = async (type) => {
    setExporting(true);
    try {
      const res = await axios.get(`${API}/revenue-report/export/${type}`, {
        params: { period, date },
        headers: getAuthHeader(),
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `revenue_${period}_${date}.${type === "csv" ? "csv" : "pdf"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`${type.toUpperCase()} berhasil diunduh`);
    } catch {
      toast.error(`Gagal mengekspor ${type.toUpperCase()}`);
    } finally {
      setExporting(false);
    }
  };

  const totals = (Array.isArray(rows) ? rows : []).reduce(
    (acc, r) => ({
      qty_standar: acc.qty_standar + (Number(r?.qty_standar) || 0),
      revenue_standar: acc.revenue_standar + (Number(r?.revenue_standar) || 0),
      qty_premium: acc.qty_premium + (Number(r?.qty_premium) || 0),
      revenue_premium: acc.revenue_premium + (Number(r?.revenue_premium) || 0),
      total_revenue: acc.total_revenue + (Number(r?.total_revenue) || 0),
    }),
    {
      qty_standar: 0,
      revenue_standar: 0,
      qty_premium: 0,
      revenue_premium: 0,
      total_revenue: 0,
    },
  );

  const periodLabel = { daily: "Jam", weekly: "Tanggal", monthly: "Tanggal" }[
    period
  ];

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h1
              className="text-xl font-black text-white"
              style={{ fontFamily: "Chivo, sans-serif" }}
            >
              Revenue Report
            </h1>
            <p className="text-zinc-500 text-xs">
              Laporan pendapatan berdasarkan kategori driver
            </p>
          </div>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-xl p-4"
      >
        <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
          <div className="flex items-center gap-2">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                onClick={() => setPeriod(p.key)}
                className={`px-4 py-2 rounded-lg text-sm font-bold transition-all ${
                  period === p.key
                    ? "bg-emerald-500 text-black"
                    : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="px-3 py-2 rounded-lg bg-zinc-950/70 border border-zinc-700 focus:border-emerald-500/50 outline-none text-zinc-100 text-sm [color-scheme:dark]"
            />
            <button
              onClick={() => handleExport("csv")}
              disabled={exporting || rows.length === 0}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 text-xs font-bold transition-all disabled:opacity-50"
            >
              <Download className="w-3.5 h-3.5" /> CSV
            </button>
            <button
              onClick={() => handleExport("pdf")}
              disabled={exporting || rows.length === 0}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-500 text-black hover:bg-emerald-400 text-xs font-bold transition-all disabled:opacity-50"
            >
              <FileDown className="w-3.5 h-3.5" /> PDF
            </button>
          </div>
        </div>
        {meta && (
          <p className="text-xs text-zinc-500 mt-3">
            Periode: <span className="text-zinc-300">{meta.date_from}</span> s/d{" "}
            <span className="text-zinc-300">{meta.date_to}</span>
          </p>
        )}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card rounded-xl overflow-hidden"
      >
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="text-emerald-500 font-mono text-sm animate-pulse">
              Memuat data...
            </div>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-zinc-500">
            <TrendingUp className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">Tidak ada data transaksi pada periode ini</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800/50 bg-zinc-900/30">
                  <th className="text-left px-4 py-3 text-label">
                    {periodLabel}
                  </th>
                  <th className="text-right px-4 py-3 text-label">
                    Qty Standar
                  </th>
                  <th className="text-right px-4 py-3 text-label">
                    Revenue Standar
                  </th>
                  <th className="text-right px-4 py-3 text-label">
                    Qty Premium
                  </th>
                  <th className="text-right px-4 py-3 text-label">
                    Revenue Premium
                  </th>
                  <th className="text-right px-4 py-3 text-label">
                    Total Revenue
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr
                    key={i}
                    className="border-b border-zinc-800/30 hover:bg-white/5 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-zinc-300">
                      {r.period_label}
                    </td>
                    <td className="px-4 py-3 text-right text-zinc-400">
                      {r.qty_standar}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-emerald-400">
                      {formatRp(r.revenue_standar)}
                    </td>
                    <td className="px-4 py-3 text-right text-zinc-400">
                      {r.qty_premium}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-sky-400">
                      {formatRp(r.revenue_premium)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs font-bold text-zinc-100">
                      {formatRp(r.total_revenue)}
                    </td>
                  </tr>
                ))}
                <tr className="border-t-2 border-emerald-500/40 bg-emerald-500/5">
                  <td className="px-4 py-3 font-bold text-emerald-400 text-xs">
                    GRAND TOTAL
                  </td>
                  <td className="px-4 py-3 text-right font-bold text-emerald-400">
                    {totals.qty_standar}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-xs font-bold text-emerald-400">
                    {formatRp(totals.revenue_standar)}
                  </td>
                  <td className="px-4 py-3 text-right font-bold text-emerald-400">
                    {totals.qty_premium}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-xs font-bold text-emerald-400">
                    {formatRp(totals.revenue_premium)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-xs font-bold text-emerald-400">
                    {formatRp(totals.total_revenue)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </motion.div>
    </div>
  );
}
