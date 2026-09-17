import sqlite3
import os
import json
from datetime import datetime, date

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "period.db"))

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_date TEXT NOT NULL UNIQUE,
        end_date TEXT,
        duration INTEGER,
        interval_days INTEGER,
        notes TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',
        is_ignored INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    
    # Check if is_ignored column exists
    cursor.execute("PRAGMA table_info(records)")
    cols = [r[1] for r in cursor.fetchall()]
    if "is_ignored" not in cols:
        try:
            cursor.execute("ALTER TABLE records ADD COLUMN is_ignored INTEGER DEFAULT 0")
        except Exception:
            pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    # Default settings (desensitized, configurable via Web UI or environment variables)
    default_settings = {
        "period_days": os.getenv("DEFAULT_PERIOD_DAYS", "28"),
        "menses_days": os.getenv("DEFAULT_MENSES_DAYS", "5"),
        "calc_mode": "standard",  # "standard" (28天), "clean_all" (平均周期)
        "auto_calc_period": "0",  # 0: standard fixed, 1: dynamic
        "email_enabled": "1",
        "remind_end_enabled": "1",
        "smtp_host": os.getenv("SMTP_HOST", "smtp.qq.com"),
        "smtp_port": os.getenv("SMTP_PORT", "465"),
        "smtp_user": os.getenv("SMTP_USER", "your_email@qq.com"),
        "smtp_pass": os.getenv("SMTP_PASS", "your_smtp_auth_code"),
        "email_to": os.getenv("EMAIL_TO", "your_partner@qq.com, your_email@qq.com"),
        "remind_days_before": os.getenv("REMIND_DAYS_BEFORE", "3"),
        "remind_time": os.getenv("REMIND_TIME", "08:00"),
        "last_reminded_cycle": "",
        "last_reminded_end_cycle": "",
        "partner_name": os.getenv("PARTNER_NAME", "老婆"),
        "wechat_enabled": "1",
        "wechat_appid": os.getenv("WECHAT_APPID", ""),
        "wechat_secret": os.getenv("WECHAT_SECRET", ""),
        "wechat_template_id": os.getenv("WECHAT_TEMPLATE_ID", "")
    }
    
    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()

def recalculate_intervals():
    """Recalculate interval_days and duration for all records ordered chronologically."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, start_date, end_date FROM records ORDER BY start_date ASC")
    rows = cursor.fetchall()
    
    prev_start = None
    for row in rows:
        r_id = row["id"]
        s_date = datetime.strptime(row["start_date"], "%Y-%m-%d").date()
        e_date = datetime.strptime(row["end_date"], "%Y-%m-%d").date() if row["end_date"] else None
        
        duration = (e_date - s_date).days + 1 if e_date else None
        interval = (s_date - prev_start).days if prev_start else None
        
        cursor.execute("""
            UPDATE records 
            SET duration = ?, interval_days = ?
            WHERE id = ?
        """, (duration, interval, r_id))
        
        prev_start = s_date
        
    conn.commit()
    conn.close()

def get_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    res = {row["key"]: row["value"] for row in cursor.fetchall()}
    conn.close()
    return res

def update_settings(data: dict):
    conn = get_db()
    cursor = conn.cursor()
    for k, v in data.items():
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()

def classify_record(r):
    """
    Classify a record into clinical/statistical categories:
    - normal: 18 <= interval <= 42, 2 <= duration <= 8
    - missed_cycle: 45 <= interval <= 60 (likely 1 missed period)
    - extended_gap: interval > 60 (pregnancy/postpartum/amenorrhea)
    - spotting: interval < 18 (intermenstrual bleeding/ovulation spotting)
    - prolonged_recording: duration > 10 (unclosed recording)
    - short_bleed: duration < 2 (spotting)
    """
    inv = r.get("interval_days")
    dur = r.get("duration")

    if inv is not None and inv >= 45:
        if inv <= 60:
            return {
                "tag": "missed_cycle",
                "tag_cn": "疑似漏记1次",
                "badge": "bg-amber-100 text-amber-800 border-amber-300",
                "color": "amber",
                "note": f"间隔 {inv} 天，约为两个正常周期（可能漏记了中间1次月经）",
                "is_clean": False
            }
        else:
            return {
                "tag": "extended_gap",
                "tag_cn": "孕产/长停经",
                "badge": "bg-purple-100 text-purple-800 border-purple-300",
                "color": "purple",
                "note": f"长期间隔 {inv} 天（备孕、孕产或长期停经）",
                "is_clean": False
            }

    if inv is not None and inv < 18:
        return {
            "tag": "spotting",
            "tag_cn": "经间/排卵出血",
            "badge": "bg-yellow-100 text-yellow-800 border-yellow-300",
            "color": "yellow",
            "note": f"间隔仅 {inv} 天，疑似排卵期出血或偶发经间期出血",
            "is_clean": False
        }

    if dur is not None and dur > 10:
        return {
            "tag": "prolonged_recording",
            "tag_cn": "打卡未结束/超长",
            "badge": "bg-rose-100 text-rose-800 border-rose-300",
            "color": "rose",
            "note": f"持续 {dur} 天，疑似未及时打卡结束日期",
            "is_clean": False
        }

    if dur is not None and dur < 2:
        return {
            "tag": "short_bleed",
            "tag_cn": "极短出血",
            "badge": "bg-orange-100 text-orange-800 border-orange-300",
            "color": "orange",
            "note": f"持续仅 {dur} 天，疑似轻微点滴出血",
            "is_clean": False
        }

    return {
        "tag": "normal",
        "tag_cn": "正常周期",
        "badge": "bg-emerald-100 text-emerald-800 border-emerald-300",
        "color": "emerald",
        "note": "周期及持续天数正常",
        "is_clean": True
    }

def get_clean_analytics():
    """Calculate clean medical statistics by excluding anomalies."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM records ORDER BY start_date DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_records = len(rows)
    if total_records == 0:
        return {
            "total_records": 0,
            "clean_count": 0,
            "anomaly_count": 0,
            "all_time_clean_avg": 27.0,
            "recent_clean_avg": 27.0,
            "avg_duration": 5.0,
            "regularity_score": 100,
            "anomalies": []
        }

    clean_intervals = []
    clean_durations = []
    anomalies = []
    duration_dist = {}

    for r in rows:
        diag = classify_record(r)
        r["diagnosis"] = diag
        dur = r.get("duration")
        inv = r.get("interval_days")

        if dur is not None and 1 <= dur <= 10:
            duration_dist[dur] = duration_dist.get(dur, 0) + 1
            clean_durations.append(dur)
        elif dur is not None:
            duration_dist[dur] = duration_dist.get(dur, 0) + 1

        if diag["is_clean"] and inv is not None:
            clean_intervals.append(inv)
        elif not diag["is_clean"]:
            anomalies.append({
                "id": r["id"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "duration": dur,
                "interval_days": inv,
                "diagnosis": diag
            })

    all_time_clean_avg = round(sum(clean_intervals) / len(clean_intervals), 1) if clean_intervals else 27.0
    recent_clean_avg = round(sum(clean_intervals[:10]) / len(clean_intervals[:10]), 1) if clean_intervals else 27.0
    avg_duration = round(sum(clean_durations) / len(clean_durations), 1) if clean_durations else 5.0
    
    # Regularity score: percentage of clean records out of records with intervals
    total_intervals = sum(1 for r in rows if r.get("interval_days") is not None)
    regularity_score = round((len(clean_intervals) / total_intervals) * 100) if total_intervals > 0 else 100

    return {
        "total_records": total_records,
        "clean_count": len(clean_intervals),
        "anomaly_count": len(anomalies),
        "all_time_clean_avg": all_time_clean_avg,
        "recent_clean_avg": recent_clean_avg,
        "avg_duration": avg_duration,
        "regularity_score": regularity_score,
        "duration_distribution": duration_dist,
        "anomalies": anomalies
    }

def get_effective_period_days():
    """
    Returns effective cycle days.
    Default mode is standard 27 days (matches mini-program and user expectation for 2026-09-17 today).
    """
    settings = get_settings()
    calc_mode = settings.get("calc_mode", "standard")
    fallback_days = int(settings.get("period_days", "27"))

    if calc_mode == "clean_all":
        analytics = get_clean_analytics()
        return round(analytics["all_time_clean_avg"])
    elif calc_mode == "clean_recent":
        analytics = get_clean_analytics()
        return round(analytics["recent_clean_avg"])
    else:
        return fallback_days
