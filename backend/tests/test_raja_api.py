"""RAJA Digital System - Backend API Tests"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_TOKEN = None
SUPERADMIN_TOKEN = None


def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()['token']
    return None


@pytest.fixture(scope="session")
def admin_token():
    return get_token("admin1@raja.id", "admin123")


@pytest.fixture(scope="session")
def superadmin_token():
    return get_token("superadmin@raja.id", "superadmin123")


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def superadmin_headers(superadmin_token):
    return {"Authorization": f"Bearer {superadmin_token}"}


# ===== AUTH TESTS =====

class TestAuth:
    """Authentication endpoint tests"""

    def test_login_admin1(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin1@raja.id", "password": "admin123"})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"

    def test_login_admin2(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin2@raja.id", "password": "admin123"})
        assert r.status_code == 200

    def test_login_admin3(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin3@raja.id", "password": "admin123"})
        assert r.status_code == 200

    def test_login_admin4(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin4@raja.id", "password": "admin123"})
        assert r.status_code == 200

    def test_login_superadmin(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "superadmin@raja.id", "password": "superadmin123"})
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["role"] == "superadmin"

    def test_login_invalid(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "bad@raja.id", "password": "wrongpass"})
        assert r.status_code == 401

    def test_auth_me(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=admin_headers)
        assert r.status_code == 200
        assert "email" in r.json()


# ===== DRIVERS TESTS =====

class TestDrivers:
    """Driver management tests"""

    def test_get_drivers(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/drivers", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_active_drivers(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/drivers/active", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert all(d['status'] == 'active' for d in data)

    def test_driver_search(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/drivers?search=Ahmad", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0

    def test_update_driver_requires_superadmin(self, admin_headers):
        r = requests.put(f"{BASE_URL}/api/drivers/driver001", json={"phone": "08123456789"}, headers=admin_headers)
        assert r.status_code == 403

    def test_suspend_driver(self, superadmin_headers):
        r = requests.patch(f"{BASE_URL}/api/drivers/driver020/suspend", headers=superadmin_headers)
        assert r.status_code == 200

    def test_activate_driver(self, superadmin_headers):
        r = requests.patch(f"{BASE_URL}/api/drivers/driver020/activate", headers=superadmin_headers)
        assert r.status_code == 200


# ===== SIJ TESTS =====

class TestSIJ:
    """SIJ transaction tests"""

    def test_get_sij(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/sij", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Verify all returned transactions are active by default
        for tx in data:
            assert tx.get("status") == "active"
    
    def test_get_sij_with_date_filter(self, admin_headers):
        """Test GET /api/sij with date filter for List SIJ page"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        r = requests.get(f"{BASE_URL}/api/sij?date={today}", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # All transactions should be for the specified date
        for tx in data:
            assert tx.get("date") == today
    
    def test_get_sij_with_include_void(self, admin_headers):
        """Test GET /api/sij with include_void parameter"""
        r = requests.get(f"{BASE_URL}/api/sij?include_void=true", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Can contain both active and void transactions
        # Verify response structure
        if len(data) > 0:
            tx = data[0]
            assert "transaction_id" in tx
            assert "driver_id" in tx
            assert "driver_name" in tx
            assert "date" in tx
            assert "time" in tx
            assert "sheets" in tx
            assert "amount" in tx
            assert "qris_ref" in tx
            assert "admin_name" in tx
            assert "status" in tx
    
    def test_get_sij_response_structure(self, admin_headers):
        """Test that SIJ response has all required fields for List SIJ page"""
        r = requests.get(f"{BASE_URL}/api/sij", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        if len(data) > 0:
            tx = data[0]
            # Required fields for List SIJ display
            required_fields = ["transaction_id", "driver_id", "driver_name", "date", 
                             "time", "sheets", "amount", "qris_ref", "admin_name", 
                             "shift", "status"]
            for field in required_fields:
                assert field in tx, f"Missing field: {field}"

    def test_create_sij(self, admin_headers):
        # Use driver that likely has no SIJ today
        r = requests.post(f"{BASE_URL}/api/sij", json={
            "driver_id": "driver045",
            "sheets": 3,
            "qris_ref": "TEST_QRIS_123456"
        }, headers=admin_headers)
        # 200 success or 400 if driver already has SIJ today
        assert r.status_code in [200, 400]
        if r.status_code == 200:
            data = r.json()
            assert "transaction_id" in data
            assert data["driver_id"] == "driver045"

    def test_sij_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/sij")
        assert r.status_code == 403

    def test_create_sij_with_future_date(self, admin_headers):
        """Test SIJ creation with a valid future date (within 7 days)"""
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        r = requests.post(f"{BASE_URL}/api/sij", json={
            "driver_id": "driver046",
            "sheets": 2,
            "qris_ref": "TEST_QRIS_FUTURE_DATE",
            "date": future_date
        }, headers=admin_headers)
        # 200 success or 400 if driver already has SIJ for that date
        assert r.status_code in [200, 400]
        if r.status_code == 200:
            data = r.json()
            assert data["date"] == future_date

    def test_create_sij_with_past_date_rejected(self, admin_headers):
        """Test that past dates are rejected"""
        from datetime import datetime, timedelta
        past_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.post(f"{BASE_URL}/api/sij", json={
            "driver_id": "driver047",
            "sheets": 2,
            "qris_ref": "TEST_QRIS_PAST_DATE",
            "date": past_date
        }, headers=admin_headers)
        assert r.status_code == 400
        assert "hari ini" in r.json().get("detail", "").lower() or "7 hari" in r.json().get("detail", "").lower()

    def test_create_sij_with_far_future_date_rejected(self, admin_headers):
        """Test that dates beyond 7 days are rejected"""
        from datetime import datetime, timedelta
        far_future_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        r = requests.post(f"{BASE_URL}/api/sij", json={
            "driver_id": "driver048",
            "sheets": 2,
            "qris_ref": "TEST_QRIS_FAR_FUTURE",
            "date": far_future_date
        }, headers=admin_headers)
        assert r.status_code == 400
        assert "7 hari" in r.json().get("detail", "").lower()


# ===== DASHBOARD TESTS =====

class TestDashboard:
    """Dashboard endpoint tests"""

    def test_admin_dashboard(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/admin", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "sij_today_shift" in data
        assert "revenue_shift" in data
        assert "active_drivers" in data
        assert "mismatch_list" in data
        assert "recent_sij" in data

    def test_superadmin_dashboard(self, superadmin_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/superadmin", headers=superadmin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "total_sij_today" in data
        assert "sij_per_shift" in data
        assert "revenue_per_admin" in data
        assert "daily_trend" in data
        assert "driver_ranking" in data
        assert "mismatch_list" in data
        assert len(data["daily_trend"]) == 7

    def test_superadmin_dashboard_blocked_for_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/superadmin", headers=admin_headers)
        assert r.status_code == 403


# ===== AUDIT TESTS =====

class TestAudit:
    """Audit log tests"""

    def test_get_audit(self, superadmin_headers):
        r = requests.get(f"{BASE_URL}/api/audit", headers=superadmin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_audit_blocked_for_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/audit", headers=admin_headers)
        assert r.status_code == 403

    def test_export_audit_csv(self, superadmin_headers):
        r = requests.get(f"{BASE_URL}/api/audit/export", headers=superadmin_headers)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")


# ===== WEEKLY REPORT TRUNCATION TESTS =====

class TestWeeklyReportTruncation:
    """
    Automated regression tests to catch report truncation bugs.

    These tests guard against hardcoded day limits (e.g. 7-day cap) being
    accidentally introduced in get_weekly_report, export_weekly_csv, or
    export_weekly_pdf.  They use April Periode 4 (22-30) as the canonical
    9-day reference case.
    """

    # ---- helpers ----

    @staticmethod
    def _csv_date_labels(csv_text: str) -> list:
        """Return the unique 'Tgl N' labels found in the CSV header row."""
        import csv as csv_mod
        import io as io_mod
        reader = csv_mod.reader(io_mod.StringIO(csv_text))
        seen = set()
        labels = []
        for row in reader:
            # The header row starts with "No", "Nama Driver", "Nopol"
            if row and row[0] == "No":
                for cell in row:
                    if cell.startswith("Tgl "):
                        # Strip the KHD/RTS suffix: "Tgl 22 KHD" -> "Tgl 22"
                        label = " ".join(cell.split()[:2])
                        if label not in seen:
                            seen.add(label)
                            labels.append(label)
                break  # only inspect the first real header row
        return labels

    @staticmethod
    def _pdf_text(pdf_bytes: bytes) -> str:
        """Extract all text from a PDF returned as bytes."""
        import io as io_mod
        import pypdf
        reader = pypdf.PdfReader(io_mod.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    # ---- JSON endpoint tests ----

    def test_weekly_report_json_april_periode4_returns_9_days(self, admin_headers):
        """GET /api/weekly-report must return exactly 9 days for Apr 22-30."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        data = r.json()
        days = data.get("days", [])
        assert len(days) == 9, (
            f"Expected 9 days for Apr 22-30, got {len(days)}: {days}"
        )

    def test_weekly_report_json_april_periode4_day_values(self, admin_headers):
        """The 9 days returned must be exactly 2026-04-22 through 2026-04-30."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        days = r.json().get("days", [])
        expected = [f"2026-04-{d:02d}" for d in range(22, 31)]
        assert days == expected, f"Day list mismatch: {days}"

    def test_weekly_report_json_driver_daily_count_matches_period(self, admin_headers):
        """Every driver row must have exactly 9 daily entries."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        drivers = r.json().get("drivers", [])
        assert len(drivers) > 0, "No drivers returned — cannot validate daily count"
        for drv in drivers:
            daily = drv.get("daily", [])
            assert len(daily) == 9, (
                f"Driver '{drv['name']}' has {len(daily)} daily entries, expected 9"
            )

    # ---- CSV export tests ----

    def test_weekly_report_csv_april_periode4_returns_200(self, admin_headers):
        """CSV export endpoint must respond 200 for Apr 22-30."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/csv",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_weekly_report_csv_april_periode4_has_9_date_columns(self, admin_headers):
        """CSV header must contain exactly 9 unique Tgl labels (Tgl 22 – Tgl 30)."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/csv",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        labels = self._csv_date_labels(r.text)
        assert len(labels) == 9, (
            f"CSV has {len(labels)} date column(s), expected 9. Found: {labels}"
        )

    def test_weekly_report_csv_april_periode4_correct_day_labels(self, admin_headers):
        """CSV date labels must be Tgl 22 through Tgl 30 in order."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/csv",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        labels = self._csv_date_labels(r.text)
        expected_labels = [f"Tgl {d}" for d in range(22, 31)]
        assert labels == expected_labels, (
            f"CSV day labels mismatch.\n  Expected: {expected_labels}\n  Got:      {labels}"
        )

    def test_weekly_report_csv_no_truncation_for_9day_period(self, admin_headers):
        """
        Generic guard: any 9-day period must produce 9 date columns.
        Uses a static date range so the test is deterministic.
        """
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/csv",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        labels = self._csv_date_labels(r.text)
        assert len(labels) >= 9, (
            f"Truncation detected: only {len(labels)} date column(s) for a 9-day period"
        )

    # ---- PDF export tests ----

    def test_weekly_report_pdf_april_periode4_returns_200(self, admin_headers):
        """PDF export endpoint must respond 200 for Apr 22-30."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/pdf",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("content-type", "")

    def test_weekly_report_pdf_april_periode4_has_9_day_labels(self, admin_headers):
        """PDF must contain exactly the 9 day labels Tgl 22–Tgl 30 and no others."""
        import re
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/pdf",
            params={"start_date": "2026-04-22", "end_date": "2026-04-30"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        text = self._pdf_text(r.content)

        expected_labels = {f"Tgl {d}" for d in range(22, 31)}

        missing = [lbl for lbl in expected_labels if lbl not in text]
        assert not missing, (
            f"PDF is missing day label(s): {sorted(missing)}. "
            "This indicates column truncation in the PDF export."
        )

        found_labels = set(re.findall(r"Tgl \d+", text))
        unexpected = found_labels - expected_labels
        assert not unexpected, (
            f"PDF contains unexpected day label(s): {sorted(unexpected)}. "
            "Expected only Tgl 22 through Tgl 30."
        )

    # ---- Parametrized tests for all four Periode types ----

    PERIODE_CASES = [
        pytest.param(
            "2026-04-01", "2026-04-07", list(range(1, 8)), 7,
            id="periode1_april_1-7",
        ),
        pytest.param(
            "2026-04-08", "2026-04-14", list(range(8, 15)), 7,
            id="periode2_april_8-14",
        ),
        pytest.param(
            "2026-04-15", "2026-04-21", list(range(15, 22)), 7,
            id="periode3_april_15-21",
        ),
        pytest.param(
            "2026-04-22", "2026-04-30", list(range(22, 31)), 9,
            id="periode4_april_22-30",
        ),
        pytest.param(
            "2026-02-22", "2026-02-28", list(range(22, 29)), 7,
            id="periode4_february_22-28",
        ),
        pytest.param(
            "2024-02-22", "2024-02-29", list(range(22, 30)), 8,
            id="periode4_february_leap_year_22-29",
        ),
    ]

    @pytest.mark.parametrize("start_date,end_date,day_numbers,expected_days", PERIODE_CASES)
    def test_weekly_report_json_periode_day_count(
        self, admin_headers, start_date, end_date, day_numbers, expected_days
    ):
        """GET /api/weekly-report must return the correct number of days for each Periode."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report",
            params={"start_date": start_date, "end_date": end_date},
            headers=admin_headers,
        )
        assert r.status_code == 200
        days = r.json().get("days", [])
        assert len(days) == expected_days, (
            f"Expected {expected_days} days for {start_date}–{end_date}, got {len(days)}: {days}"
        )

    @pytest.mark.parametrize("start_date,end_date,day_numbers,expected_days", PERIODE_CASES)
    def test_weekly_report_json_periode_day_values(
        self, admin_headers, start_date, end_date, day_numbers, expected_days
    ):
        """Day list must match the exact dates for each Periode."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report",
            params={"start_date": start_date, "end_date": end_date},
            headers=admin_headers,
        )
        assert r.status_code == 200
        days = r.json().get("days", [])
        year, month, _ = start_date.split("-")
        expected = [f"{year}-{month}-{d:02d}" for d in day_numbers]
        assert days == expected, (
            f"Day list mismatch for {start_date}–{end_date}.\n"
            f"  Expected: {expected}\n  Got:      {days}"
        )

    @pytest.mark.parametrize("start_date,end_date,day_numbers,expected_days", PERIODE_CASES)
    def test_weekly_report_json_driver_daily_count_all_periodes(
        self, admin_headers, start_date, end_date, day_numbers, expected_days
    ):
        """Every driver row must have exactly the right number of daily entries per Periode."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report",
            params={"start_date": start_date, "end_date": end_date},
            headers=admin_headers,
        )
        assert r.status_code == 200
        drivers = r.json().get("drivers", [])
        assert len(drivers) > 0, "No drivers returned — cannot validate daily count"
        for drv in drivers:
            daily = drv.get("daily", [])
            assert len(daily) == expected_days, (
                f"Driver '{drv['name']}' has {len(daily)} daily entries, "
                f"expected {expected_days} for {start_date}–{end_date}"
            )

    @pytest.mark.parametrize("start_date,end_date,day_numbers,expected_days", PERIODE_CASES)
    def test_weekly_report_csv_periode_column_count(
        self, admin_headers, start_date, end_date, day_numbers, expected_days
    ):
        """CSV header must contain exactly the correct number of Tgl labels for each Periode."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/csv",
            params={"start_date": start_date, "end_date": end_date},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        labels = self._csv_date_labels(r.text)
        assert len(labels) == expected_days, (
            f"CSV has {len(labels)} date column(s) for {start_date}–{end_date}, "
            f"expected {expected_days}. Found: {labels}"
        )

    @pytest.mark.parametrize("start_date,end_date,day_numbers,expected_days", PERIODE_CASES)
    def test_weekly_report_csv_periode_correct_day_labels(
        self, admin_headers, start_date, end_date, day_numbers, expected_days
    ):
        """CSV date labels must match the exact Tgl numbers for each Periode, in order."""
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/csv",
            params={"start_date": start_date, "end_date": end_date},
            headers=admin_headers,
        )
        assert r.status_code == 200
        labels = self._csv_date_labels(r.text)
        expected_labels = [f"Tgl {d}" for d in day_numbers]
        assert labels == expected_labels, (
            f"CSV day labels mismatch for {start_date}–{end_date}.\n"
            f"  Expected: {expected_labels}\n  Got:      {labels}"
        )

    @pytest.mark.parametrize("start_date,end_date,day_numbers,expected_days", PERIODE_CASES)
    def test_weekly_report_pdf_periode_has_all_day_labels(
        self, admin_headers, start_date, end_date, day_numbers, expected_days
    ):
        """PDF must contain all expected Tgl labels and no labels outside the Periode."""
        import re
        r = requests.get(
            f"{BASE_URL}/api/weekly-report/export/pdf",
            params={"start_date": start_date, "end_date": end_date},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("content-type", "")
        text = self._pdf_text(r.content)

        expected_labels = {f"Tgl {d}" for d in day_numbers}

        missing = [lbl for lbl in expected_labels if lbl not in text]
        assert not missing, (
            f"PDF is missing day label(s) for {start_date}–{end_date}: {sorted(missing)}. "
            "This indicates column truncation in the PDF export."
        )

        found_labels = set(re.findall(r"Tgl \d+", text))
        unexpected = found_labels - expected_labels
        assert not unexpected, (
            f"PDF contains unexpected day label(s) for {start_date}–{end_date}: {sorted(unexpected)}. "
            f"Expected only {sorted(expected_labels)}."
        )
