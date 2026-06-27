# Alliansi SMF

## Overview
Alliansi SMF - A driver management and SIJ (Surat Izin Jalan) transaction system for Soetta Airport. Built with a React frontend and FastAPI backend using Supabase PostgreSQL database.

## Project Architecture

### Frontend (React + CRACO)
- **Location**: `frontend/`
- **Port**: 5000 (dev server, bound to 0.0.0.0)
- **Framework**: React 19 with Create React App + CRACO
- **Styling**: Tailwind CSS + Radix UI components (shadcn/ui pattern)
- **State**: React Context API (AuthContext)
- **Routing**: react-router-dom v7
- **API calls**: Axios, relative paths proxied to backend via CRA proxy

### Backend (FastAPI)
- **Location**: `backend/`
- **Port**: 8000 (localhost only)
- **Database**: Supabase PostgreSQL (asyncpg driver with SSL)
- **Auth**: JWT tokens with bcrypt password hashing
- **API prefix**: `/api`

### Database
- **Type**: PostgreSQL (Supabase, via SUPABASE_DATABASE_URL env var, falls back to DATABASE_URL)
- **Tables**: users, drivers, sij_transactions, audit_log, ritase, driver_absences
- **Connection**: asyncpg with SSL (ssl.CERT_NONE for Supabase compatibility)
- **Auto-seed**: On first startup, seeds 5 admin users, 50 drivers, ~200 sample transactions

### Key Files
- `backend/server.py` - Full backend API
- `frontend/src/context/AuthContext.jsx` - Auth context (API = '/api')
- `frontend/src/pages/RitaseList.jsx` - Ritase CRUD page
- `frontend/src/pages/SIJList.jsx` - SIJ List with full CRUD
- `frontend/craco.config.js` - Dev server config (port 5000, allowedHosts: all)
- `frontend/src/setupProxy.js` - CRA proxy config (proxies /api and /pool-dashboard to backend)
- `frontend/package.json` - Frontend dependencies

## Login Credentials
- Admin: admin1@raja.id / admin123 (Shift1)
- Admin: admin3@raja.id / admin123 (Shift2)
- Super Admin: superadmin@raja.id / superadmin123

## Auth Roles
- **superadmin**: Full access to all features and pages
- **admin**: Access to operational pages (Dashboard, SIJ, Ritase, Laporan, Audit, Pool Dashboard) + write operations
- **viewer**: Read-only access to exactly 5 pages: Dashboard, List SIJ, Data Driver, Laporan Mingguan, Revenue Report
  - Frontend: ViewerGuard in App.js redirects viewer away from non-allowed routes; sidebar only shows 5 items
  - Dashboard: Viewer sees SuperAdmin dashboard (same as superadmin) with suspend buttons hidden
  - Backend: Non-viewer GET endpoints (ritase, audit, pool-dashboard) use `require_admin`; GET /dashboard/superadmin allows superadmin+viewer; all write endpoints use `require_admin`/`require_superadmin`
  - UI: Action buttons (add/edit/delete/suspend) hidden via `isViewer` checks in SIJList, Drivers, LaporanMingguan, SuperAdminDashboard

## Recent Changes
- **2026-04-09**: Revamped Laporan Mingguan → Laporan Bulanan (Monthly Period Report)
  - Backend: New `GET /api/monthly-report?month=YYYY-MM` endpoint aggregating KHD & RTS into 4 fixed date-range periods per month (Periode 1: 1-7, Periode 2: 8-14, Periode 3: 15-21, Periode 4: 22-end)
  - Backend: New `GET /api/monthly-report/export/csv` and `/export/pdf` endpoints with 4-period columns
  - Frontend `LaporanMingguan.jsx`: Month/Year picker (prev/next/this month), 4-period table with KHD|RTS per cell, fraud detection per period (red highlight), low-KHD alert (< 20 for the month), updated CSV/PDF exports
  - Per-cell absence/ritase edit modals removed (not applicable to aggregated period view)
  - Low KHD threshold changed from 5 (weekly) to 20 (monthly)
- **2026-02-25**: Added configurable API base URL for external frontend deployments (e.g. Vercel)
  - `AuthContext.jsx`: API URL reads from `REACT_APP_API_URL` env var, falls back to `/api`
  - For Vercel: Set `REACT_APP_API_URL=https://koperasiraja.replit.app` in Vercel env vars
  - CORS already allows all origins (`allow_origins=["*"]`)
- **2026-02-25**: Migrated database from Replit PostgreSQL to Supabase PostgreSQL
  - Updated `backend/server.py` to use `SUPABASE_DATABASE_URL` env var (falls back to `DATABASE_URL`)
  - Added SSL context and PgBouncer compatibility (statement_cache_size=0)
  - Tables auto-created and seeded on first startup via existing `create_tables()` and `seed_initial_data()`
- **2026-02-24**: Added Laporan Mingguan (Weekly Report) module
  - Backend: GET `/api/weekly-report?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` - aggregates KHD (attendance) and RTS (trips) per driver per day
  - Backend: GET `/api/weekly-report/export/csv` and `/api/weekly-report/export/pdf` - export with fraud highlighting
  - Frontend: New `LaporanMingguan.jsx` page at `/laporan-mingguan` route
  - Fraud detection: RED highlight when KHD=0 AND RTS>0 (trip without SIJ purchase)
  - Low attendance alert: RED when Total_KHD < 5 for the week
  - Week navigation (prev/next/this week), search/filter, CSV/PDF export
  - Sidebar: "Laporan Mingguan" menu item (SuperAdmin only) with CalendarRange icon
- **2026-02-24**: Renamed driver category 'Regular'/'reg' to 'Standar'/'standar'
  - Updated all frontend files (Drivers, SIJInput, SIJList, RitaseList)
  - Updated backend PRICE_MAP and defaults
  - Migrated 33 drivers + 129 SIJ transactions in database
  - Kept 'reg' as fallback alias in PRICE_MAP for safety
- **2026-02-24**: Added User Management CRUD (SuperAdmin only)
  - Full CRUD: GET/POST/PUT/DELETE `/api/users` endpoints
  - bcrypt password hashing, account deletion protection
  - New `UserManagement.jsx` page at `/user-management` route
- **2026-02-24**: Added Ritase module + full SIJ CRUD
  - New `ritase` database table (driver_id, date, trip_details, origin, destination, passengers, notes, admin tracking)
  - Full Ritase CRUD: GET/POST/PUT/DELETE `/api/ritase` + `/api/ritase/{id}`
  - Ritase PDF/CSV export: `/api/ritase/export/csv`, `/api/ritase/export/pdf`
  - New sidebar menu: "List Ritase Driver" at `/ritase` route
  - Dashboard widget: "Ranking Driver Berdasarkan Ritase" (top 10 by monthly trip count)
  - Dashboard KPI: "Ritase Hari Ini" card
  - SIJ full CRUD: Added PUT `/api/sij/{id}` for update, + Tambah SIJ button, Edit/Delete icons in actions column
  - Date range filtering and search for Ritase
- **2026-02-24**: Added export and CRUD features
  - PDF/CSV export for Drivers table (`/api/drivers/export/csv`, `/api/drivers/export/pdf`)
  - PDF/CSV export for SIJ transactions (`/api/sij/export/csv`, `/api/sij/export/pdf`)
  - SIJ date range filtering (`date_from`, `date_to` params)
  - Server-side sorting for Drivers, SIJ, Audit (`sort_by`, `sort_dir` params)
  - SuperAdmin CRUD: Create driver (`POST /api/drivers`), Delete driver (`DELETE /api/drivers/{id}`), Delete SIJ (`DELETE /api/sij/{id}`)
  - Audit log opened to all authenticated users
  - Removed dashboard widgets: Proyeksi Bulan, Revenue per Admin, Ranking Driver
  - Uses reportlab for PDF generation
- **2026-02-24**: Migrated from MongoDB to Replit PostgreSQL
  - Replaced motor/pymongo with asyncpg
  - All MongoDB queries converted to SQL
  - Removed MONGO_URL dependency
  - Frontend API changed from env-var-based URL to relative '/api' path
  - Added CRA proxy to forward /api requests to backend on port 8000

## Public Routes
- `/pool-dashboard` — Pool Dashboard (Alliansi SMF Command Center) for TV display. Server-side rendered HTML page served directly by the backend (no React needed). No login required. Backend `GET /api/pool-dashboard` is also public (no auth). Data is pre-rendered on page load, auto-refreshes every 30 seconds via XHR.

## Route Ordering Note
In FastAPI, static routes (e.g., `/drivers/export/csv`, `/ritase/export/csv`) must be defined BEFORE parameterized routes (e.g., `/drivers/{driver_id}`, `/ritase/{ritase_id}`) to avoid path conflicts.

## User Preferences
- Do not spend time on CSS/Styling - focus on backend endpoints and basic logic only

## Workflow
- Single workflow "Start application" runs both backend (uvicorn on port 8000) and frontend (craco on port 5000)
