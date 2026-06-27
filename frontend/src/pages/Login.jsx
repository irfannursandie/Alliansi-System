import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Eye, EyeOff, LogIn } from "lucide-react";
import { motion } from "framer-motion";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) {
      toast.error("Username dan password harus diisi");
      return;
    }
    setLoading(true);
    try {
      const user = await login(email, password);
      toast.success(`Selamat datang, ${user.name}!`);
      navigate("/dashboard");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login gagal");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center relative overflow-hidden"
      style={{
        background: "linear-gradient(135deg, #020d18 0%, #041424 40%, #071a2e 70%, #030e1a 100%)",
      }}
    >
      {/* Subtle grid overlay */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(16,185,129,1) 1px, transparent 1px), linear-gradient(90deg, rgba(16,185,129,1) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      {/* Glow blobs */}
      <div className="absolute top-1/4 left-1/4 w-80 h-80 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-sky-500/5 rounded-full blur-3xl pointer-events-none" />

      {/* Card */}
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-md mx-4"
      >
        <div className="glass-card rounded-2xl p-8 border border-white/10">
          {/* Logo */}
          <div className="flex items-center gap-3 mb-8">
            <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0 overflow-hidden">
              <img
                src="/logo-alliansi-smf.png"
                alt="Alliansi SMF"
                className="w-11 h-11 object-contain"
              />
            </div>
            <div>
              <h1
                className="text-2xl font-black text-white leading-tight"
                style={{ fontFamily: "Chivo, sans-serif" }}
              >
                Alliansi SMF
              </h1>
              <p className="text-zinc-400 text-xs">
                Driver Management System — Soekarno-Hatta
              </p>
            </div>
          </div>

          <h2 className="text-lg font-bold text-zinc-100 mb-1">
            Masuk ke Dashboard
          </h2>
          <p className="text-zinc-500 text-sm mb-6">
            Masukkan kredensial akun Anda
          </p>

          <form
            onSubmit={handleSubmit}
            className="space-y-4"
            data-testid="login-form"
          >
            <div>
              <label className="text-label block mb-1.5">Username</label>
              <input
                data-testid="email-input"
                type="text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Masukkan username"
                className="w-full px-4 py-2.5 rounded-lg bg-zinc-950/70 border border-zinc-700 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 outline-none text-zinc-100 placeholder:text-zinc-600 text-sm transition-all"
              />
            </div>
            <div>
              <label className="text-label block mb-1.5">Password</label>
              <div className="relative">
                <input
                  data-testid="password-input"
                  type={showPwd ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-4 py-2.5 pr-10 rounded-lg bg-zinc-950/70 border border-zinc-700 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 outline-none text-zinc-100 placeholder:text-zinc-600 text-sm transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  {showPwd ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>
            <button
              data-testid="login-submit-button"
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-gradient-to-r from-emerald-600 to-sky-600 text-white font-bold text-sm hover:from-emerald-500 hover:to-sky-500 hover:shadow-[0_0_24px_rgba(16,185,129,0.35)] transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
              ) : (
                <>
                  <LogIn className="w-4 h-4" />
                  Masuk
                </>
              )}
            </button>
          </form>
        </div>
      </motion.div>
    </div>
  );
}
