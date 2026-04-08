import json
import math
import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://api:8000")

st.set_page_config(page_title="CONSUMA - API CRON JOB TOOL", layout="wide")
st.title("🚀 API CRON JOB TOOL")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def api_get(path: str, params: dict = None):
    """GET from the API with a consistent timeout and error propagation."""
    return requests.get(f"{API_URL}{path}", params=params, timeout=5)


def api_post(path: str, **kwargs):
    return requests.post(f"{API_URL}{path}", timeout=5, **kwargs)


def api_delete(path: str):
    return requests.delete(f"{API_URL}{path}", timeout=5)


# ---------------------------------------------------------------------------
# Top-level metrics bar
# ---------------------------------------------------------------------------

try:
    stats = api_get("/metrics/stats").json()
    runs_all = api_get("/runs/").json()
    interrupted_count = sum(1 for r in runs_all if r["status"] == "INTERRUPTED")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Runs", stats.get("total_runs", 0))
    m2.metric("Success Rate", stats.get("success_rate", "0%"))
    m3.metric("Active Schedules", stats.get("active_schedules", 0))
    m4.metric("Crashes Recovered", interrupted_count, delta="Auto-Handled")
except requests.exceptions.ConnectionError:
    st.warning("⚠️ Cannot reach the API — is it running?")
except Exception as exc:
    st.warning(f"⚠️ Metrics unavailable: {exc}")

tabs = st.tabs(["🎯 Targets", "📅 Schedules", "📊 Live Runs", "📈 System Metrics"])


# ---------------------------------------------------------------------------
# Tab 1 — Targets
# ---------------------------------------------------------------------------

with tabs[0]:
    st.header("Configure Request Targets")

    with st.form("target_form"):
        url = st.text_input("URL", placeholder="https://httpbin.org/get")
        method = st.selectbox("Method", ["GET", "POST", "PUT", "DELETE"])
        headers_raw = st.text_area("Headers (JSON)", value="{}")

        if st.form_submit_button("Create Target"):
            # Validate URL is not empty before hitting the API.
            if not url.strip():
                st.error("URL cannot be empty.")
            else:
                # Use json.loads — eval() executes arbitrary Python code.
                try:
                    headers_parsed = json.loads(headers_raw)
                except json.JSONDecodeError as exc:
                    st.error(f"Headers must be valid JSON: {exc}")
                    headers_parsed = None

                if headers_parsed is not None:
                    try:
                        res = api_post(
                            "/targets/",
                            json={"url": url.strip(), "method": method, "headers": headers_parsed},
                        )
                        if res.status_code == 201:
                            st.rerun()
                        else:
                            st.error(f"API error {res.status_code}: {res.text}")
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot reach the API.")
                    except Exception as exc:
                        st.error(f"Unexpected error: {exc}")

    st.subheader("Existing Targets")
    try:
        targets = api_get("/targets/").json()
        if not targets:
            st.info("No targets created yet.")
        for t in targets:
            col1, col2 = st.columns([9, 1])
            col1.code(f"{t['method']} | {t['url']}")
            if col2.button("🗑️", key=f"del_t_{t['id']}"):
                try:
                    res = api_delete(f"/targets/{t['id']}")
                    if res.status_code == 200:
                        st.rerun()
                    else:
                        st.error(f"Delete failed ({res.status_code}): {res.text}")
                except Exception as exc:
                    st.error(f"Error: {exc}")
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API.")
    except Exception as exc:
        st.error(f"Could not load targets: {exc}")


# ---------------------------------------------------------------------------
# Tab 2 — Schedules
# ---------------------------------------------------------------------------

with tabs[1]:
    st.header("Schedule a Request")

    try:
        targets = api_get("/targets/").json()

        if not targets:
            st.warning("Create a Target first.")
        else:
            target_options = {f"{t['method']} - {t['url']}": t["id"] for t in targets}
            target_lookup = {t["id"]: f"{t['method']} | {t['url']}" for t in targets}

            c1, c2 = st.columns(2)
            with c1:
                sel_t = st.selectbox("Select Target", options=list(target_options.keys()))
                interval = st.number_input("Interval (Seconds)", min_value=1, value=60)
            with c2:
                duration = st.number_input("Window/Duration (Seconds, 0 = unlimited)", min_value=0, value=0)

            if st.button("Create Schedule"):
                try:
                    res = api_post(
                        "/schedules/",
                        json={
                            "target_id": target_options[sel_t],
                            "interval_seconds": int(interval),
                            "duration_seconds": int(duration) if duration > 0 else None,
                        },
                    )
                    if res.status_code == 201:
                        st.rerun()
                    else:
                        st.error(f"API error {res.status_code}: {res.text}")
                except Exception as exc:
                    st.error(f"Error: {exc}")

            st.divider()

            try:
                schedules = api_get("/schedules/").json()
                if not schedules:
                    st.info("No schedules yet.")

                for s in schedules:
                    t_info = target_lookup.get(s["target_id"], "Unknown Target")
                    created_at = s.get("created_at", "N/A")
                    time_str = (
                        created_at.split("T")[1].split(".")[0]
                        if "T" in str(created_at)
                        else "N/A"
                    )
                    status_icon = "🟢" if s["is_active"] else "⏸️"
                    expander_label = (
                        f"{status_icon} ID: {s['id']} | {t_info} | {s['interval_seconds']}s | Created: {time_str}"
                    )

                    with st.expander(expander_label):
                        col1, col2, col3 = st.columns([1, 1, 4])

                        if s["is_active"]:
                            if col1.button("Pause", key=f"p_{s['id']}"):
                                try:
                                    api_post(f"/schedules/{s['id']}/pause")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Error: {exc}")
                        else:
                            if col1.button("Resume", key=f"r_{s['id']}"):
                                try:
                                    api_post(f"/schedules/{s['id']}/resume")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Error: {exc}")

                        if col2.button("🗑️ Delete", key=f"del_s_{s['id']}"):
                            try:
                                res = api_delete(f"/schedules/{s['id']}")
                                if res.status_code == 200:
                                    st.rerun()
                                else:
                                    st.error(f"Delete failed ({res.status_code}): {res.text}")
                            except Exception as exc:
                                st.error(f"Error: {exc}")

            except Exception as exc:
                st.error(f"Could not load schedules: {exc}")

    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API.")
    except Exception as exc:
        st.error(f"Error: {exc}")


# ---------------------------------------------------------------------------
# Tab 3 — Live Runs (paginated)
# ---------------------------------------------------------------------------

with tabs[2]:
    st.header("Execution Log")

    f_col1, f_col2, f_col3 = st.columns([2, 2, 1])
    filter_id = f_col1.number_input("Filter by Schedule ID", min_value=0, step=1, value=0)
    filter_status = f_col2.selectbox(
        "Filter by Status",
        ["All", "SUCCESS", "FAILURE", "RUNNING", "PENDING", "INTERRUPTED"],
    )
    if f_col3.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    try:
        params = {}
        if filter_id > 0:
            params["schedule_id"] = int(filter_id)
        if filter_status != "All":
            params["status"] = filter_status

        runs = api_get("/runs/", params=params).json()

        if not runs:
            st.info("No runs found.")
        else:
            df = pd.DataFrame(runs)

            # Sort ascending by ID (oldest first).
            if "id" in df.columns:
                df = df.sort_values(by="id", ascending=True)

            # Pagination
            items_per_page = 20
            total_items = len(df)
            total_pages = max(1, math.ceil(total_items / items_per_page))

            p_col1, p_col2 = st.columns([1, 5])
            page_num = p_col1.number_input("Page", min_value=1, max_value=total_pages, value=1)

            start_idx = (page_num - 1) * items_per_page
            end_idx = start_idx + items_per_page
            df_page = df.iloc[start_idx:end_idx]

            id_min = int(df_page["id"].min()) if not df_page.empty else "-"
            id_max = int(df_page["id"].max()) if not df_page.empty else "-"
            p_col2.write(f"Page {page_num} of {total_pages} (Run IDs {id_min} – {id_max})")

            def color_status(val: str) -> str:
                return {
                    "SUCCESS": "background-color: #d4edda; color: #155724",
                    "FAILURE": "background-color: #f8d7da; color: #721c24",
                    "RUNNING": "background-color: #fff3cd; color: #856404",
                    "INTERRUPTED": "background-color: #e2e3e5; color: #383d41",
                    "PENDING": "background-color: #cce5ff; color: #004085",
                }.get(val, "")

            st.dataframe(
                df_page.style.map(color_status, subset=["status"]),
                use_container_width=True,
                hide_index=True,
            )

    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API.")
    except Exception as exc:
        st.error(f"Error loading runs: {exc}")


# ---------------------------------------------------------------------------
# Tab 4 — System Metrics (Prometheus)
# ---------------------------------------------------------------------------

with tabs[3]:
    st.header("Prometheus Metrics")

    try:
        raw_metrics = api_get("/metrics").text

        def find_metric(name: str, text: str) -> str:
            for line in text.splitlines():
                if line.startswith(name) and not line.startswith("#"):
                    parts = line.split()
                    # Prometheus text format: metric_name [labels] value [timestamp]
                    # The value is always the last or second-to-last token.
                    return parts[1] if len(parts) >= 2 else "N/A"
            return "N/A"

        mem_raw = find_metric("process_resident_memory_bytes", raw_metrics)
        cpu_raw = find_metric("process_cpu_seconds_total", raw_metrics)
        fds_raw = find_metric("process_open_fds", raw_metrics)

        c1, c2, c3 = st.columns(3)
        with c1:
            try:
                st.metric("Memory", f"{float(mem_raw) / (1024 * 1024):.2f} MB")
            except ValueError:
                st.metric("Memory", "N/A")
        with c2:
            st.metric("CPU Time", f"{cpu_raw}s")
        with c3:
            st.metric("Open FDs", fds_raw)

        st.code(raw_metrics, language="text")

    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API.")
    except Exception as exc:
        st.error(f"Metrics offline: {exc}")