import "@/App.css";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  Outlet,
} from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "sonner";
import Login from "@/pages/Login";
import AdminDashboard from "@/pages/AdminDashboard";
import SuperAdminDashboard from "@/pages/SuperAdminDashboard";
import SIJInput from "@/pages/SIJInput";
import SIJList from "@/pages/SIJList";
import Drivers from "@/pages/Drivers";
import AuditLog from "@/pages/AuditLog";
import RitaseList from "@/pages/RitaseList";
import UserManagement from "@/pages/UserManagement";
import LaporanMingguan from "@/pages/LaporanMingguan";
import RevenueReport from "@/pages/RevenueReport";
import Layout from "@/components/Layout";
import PoolDashboard from "@/pages/PoolDashboard";

const VIEWER_ALLOWED_PATHS = ["/dashboard", "/sij-list", "/drivers", "/laporan-mingguan", "/revenue-report", "/"];

const PrivateRoute = () => {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="flex items-center justify-center h-screen bg-zinc-950">
        <div className="text-emerald-500 font-mono text-sm animate-pulse">
          Memuat Alliansi SMF...
        </div>
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
};

const ViewerGuard = ({ children }) => {
  const { user } = useAuth();
  if (user?.role === "viewer") return <Navigate to="/dashboard" replace />;
  return children;
};

const DashboardPage = () => {
  const { user } = useAuth();
  if (user?.role === "superadmin" || user?.role === "viewer") return <SuperAdminDashboard />;
  return <AdminDashboard />;
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster theme="dark" position="top-right" richColors />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard-pool" element={<PoolDashboard />} />
          <Route element={<PrivateRoute />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/sij" element={<ViewerGuard><SIJInput /></ViewerGuard>} />
              <Route path="/sij-list" element={<SIJList />} />
              <Route path="/ritase" element={<ViewerGuard><RitaseList /></ViewerGuard>} />
              <Route path="/drivers" element={<Drivers />} />
              <Route path="/audit" element={<ViewerGuard><AuditLog /></ViewerGuard>} />
              <Route path="/user-management" element={<ViewerGuard><UserManagement /></ViewerGuard>} />
              <Route path="/laporan-mingguan" element={<LaporanMingguan />} />
              <Route path="/revenue-report" element={<RevenueReport />} />
              
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
