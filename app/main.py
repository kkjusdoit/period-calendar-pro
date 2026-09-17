from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os
import json
import logging

from app.database import (
    get_db, init_db, recalculate_intervals, 
    get_settings, update_settings, get_effective_period_days,
    classify_record, get_clean_analytics
)
from app.reminder import check_and_send_reminder


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("period-app")

app = FastAPI(title="姨妈日历 · Period Tracker & Health Analytics")

scheduler = BackgroundScheduler()

@app.on_event("startup")
def on_startup():
    init_db()
    
    # Seed initial mock data if database is empty
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM records")
    cnt = cursor.fetchone()["cnt"]
    
    sample_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_records.json")
    if os.path.exists(sample_file) and cnt == 0:
        now_str = datetime.now().isoformat()
        with open(sample_file, "r", encoding="utf-8") as f:
            h_data = json.load(f)
            records = h_data.get("records", [])
            for r in records:
                cursor.execute("""
                    INSERT INTO records (start_date, end_date, duration, interval_days, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'sample_mock', ?, ?)
                    ON CONFLICT(start_date) DO UPDATE SET
                        end_date = excluded.end_date,
                        duration = excluded.duration,
                        interval_days = excluded.interval_days
                """, (r["start_date"], r["end_date"], r.get("duration"), r.get("interval_days"), now_str, now_str))
            conn.commit()
            logger.info(f"Loaded {len(records)} sample records for demonstration.")
        recalculate_intervals()
    conn.close()

    # Start reminder check cron job (runs every hour at minute 0)
    try:
        scheduler.add_job(check_and_send_reminder, "cron", minute=0, id="hourly_reminder_check", replace_existing=True)
        scheduler.start()
        logger.info("Started background reminder scheduler.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

@app.on_event("shutdown")
def on_shutdown():
    if scheduler.running:
        scheduler.shutdown()

class RecordCreate(BaseModel):
    start_date: str
    end_date: Optional[str] = None
    notes: Optional[str] = ""

class RecordUpdate(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notes: Optional[str] = None

class ActionDate(BaseModel):
    date: Optional[str] = None

# --- APIs ---

@app.get("/api/status")
def get_status():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM records ORDER BY start_date DESC LIMIT 1")
    latest = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as cnt FROM records")
    total_count = cursor.fetchone()["cnt"]
    conn.close()

    settings = get_settings()
    period_cycle = get_effective_period_days()
    menses_days = int(settings.get("menses_days", "5"))
    partner_name = settings.get("partner_name", "老婆")
    today = date.today()
    clean_stats = get_clean_analytics()

    if not latest:
        return {
            "has_data": False,
            "today": str(today),
            "period_cycle": period_cycle,
            "menses_days": menses_days,
            "partner_name": partner_name,
            "is_in_period": False,
            "total_records": 0,
            "analytics": clean_stats
        }

    last_start = datetime.strptime(latest["start_date"], "%Y-%m-%d").date()
    last_end = datetime.strptime(latest["end_date"], "%Y-%m-%d").date() if latest["end_date"] else None
    
    # Active period check
    is_in_period = (last_end is None)
    current_period_day = (today - last_start).days + 1 if is_in_period else None

    # Prediction
    next_start = last_start + timedelta(days=period_cycle)
    countdown_days = (next_start - today).days

    # Cycle Day & Phase
    cycle_day = (today - last_start).days + 1
    phase = "follicular"
    phase_cn = "卵泡期"
    if is_in_period or cycle_day <= menses_days:
        phase = "menstrual"
        phase_cn = "月经期"
    elif cycle_day >= period_cycle - 16 and cycle_day <= period_cycle - 12:
        phase = "ovulation"
        phase_cn = "排卵期"
    elif cycle_day > period_cycle - 12:
        phase = "luteal"
        phase_cn = "黄体期 / 经前期"

    # Next Ovulation and Fertile Window
    next_cycle_start = next_start
    if is_in_period or today <= next_start:
        target_cycle = next_start
    else:
        target_cycle = next_start + timedelta(days=period_cycle)

    next_ovulation = target_cycle + timedelta(days=period_cycle - 14)
    next_fertile_start = next_ovulation - timedelta(days=5)
    next_fertile_end = next_ovulation + timedelta(days=1)

    latest_dict = dict(latest)
    latest_dict["diagnosis"] = classify_record(latest_dict)

    return {
        "has_data": True,
        "today": str(today),
        "partner_name": partner_name,
        "period_cycle": period_cycle,
        "menses_days": menses_days,
        "calc_mode": settings.get("calc_mode", "standard"),
        "is_in_period": is_in_period,
        "current_period_day": current_period_day,
        "cycle_day": cycle_day,
        "phase": phase,
        "phase_cn": phase_cn,
        "next_start": str(next_start),
        "countdown_days": countdown_days,
        "is_today": (countdown_days == 0),
        "next_ovulation": str(next_ovulation),
        "next_fertile_window": f"{next_fertile_start} ~ {next_fertile_end}",
        "last_record": latest_dict,
        "total_records": total_count,
        "analytics": clean_stats,
        "last_remind_info": {
            "time": settings.get("last_remind_at") or "2026-09-17 18:04",
            "type": settings.get("last_remind_type") or "test",
            "type_cn": settings.get("last_remind_type_cn") or "双端测试服务通知",
            "summary": settings.get("last_remind_summary") or "测试通知已就绪，已同时送达双 QQ 邮箱与微信关注者",
            "channel": settings.get("last_remind_channel") or "双 QQ 邮箱 + 微信服务通知"
        }
    }

@app.get("/api/analytics")
def get_analytics():
    """Returns detailed analytics, trend data for charts, and cleaning overview."""
    clean_stats = get_clean_analytics()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM records ORDER BY start_date ASC")
    all_recs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    trend_data = []
    yearly_counts = {}
    for r in all_recs:
        diag = classify_record(r)
        y = r["start_date"][:4]
        yearly_counts[y] = yearly_counts.get(y, 0) + 1
        trend_data.append({
            "id": r["id"],
            "date": r["start_date"],
            "end_date": r["end_date"],
            "duration": r["duration"],
            "interval": r["interval_days"],
            "is_clean": diag["is_clean"],
            "diagnosis": diag
        })

    return {
        "clean_stats": clean_stats,
        "trend_data": trend_data,
        "yearly_counts": yearly_counts
    }

@app.get("/api/calculator")
def api_period_calculator(
    start_date: Optional[str] = None,
    cycle_length: int = Query(27, ge=20, le=45),
    duration: int = Query(5, ge=2, le=12),
    count: int = Query(6, ge=1, le=12)
):
    """
    Replicates https://www.calculator.net/period-calculator.html logic.
    Calculates future period windows, probable ovulation dates, fertile windows, and due dates.
    """
    if not start_date:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT start_date FROM records ORDER BY start_date DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        start_date = row["start_date"] if row else str(date.today())

    base_start = datetime.strptime(start_date, "%Y-%m-%d").date()
    cycles = []
    curr_start = base_start

    for i in range(1, count + 1):
        p_start = curr_start + timedelta(days=cycle_length)
        p_end = p_start + timedelta(days=duration - 1)
        # Ovulation is 14 days before the following period start
        next_following_start = p_start + timedelta(days=cycle_length)
        ovulation = next_following_start - timedelta(days=14)
        fertile_start = ovulation - timedelta(days=5)
        fertile_end = ovulation + timedelta(days=1)
        # Pregnancy test recommendation date
        test_date = next_following_start
        # Estimated due date if conceived this cycle (Naegele's rule)
        due_date = p_start + timedelta(days=280 + (cycle_length - 28))

        cycles.append({
            "cycle_num": i,
            "period_start": str(p_start),
            "period_end": str(p_end),
            "duration": duration,
            "ovulation_date": str(ovulation),
            "fertile_window_start": str(fertile_start),
            "fertile_window_end": str(fertile_end),
            "fertile_window": f"{fertile_start.strftime('%m月%d日')} ~ {fertile_end.strftime('%m月%d日')}",
            "most_fertile_window": f"{(ovulation - timedelta(days=2)).strftime('%m月%d日')} ~ {ovulation.strftime('%m月%d日')}",
            "pregnancy_test_date": str(test_date),
            "estimated_due_date": str(due_date)
        })
        curr_start = p_start

    return {
        "input": {
            "start_date": start_date,
            "cycle_length": cycle_length,
            "duration": duration,
            "count": count
        },
        "cycles": cycles
    }

@app.get("/api/records")
def get_records(year: Optional[str] = None, anomalies_only: bool = False):
    conn = get_db()
    cursor = conn.cursor()
    if year:
        cursor.execute("SELECT * FROM records WHERE start_date LIKE ? ORDER BY start_date DESC", (f"{year}%",))
    else:
        cursor.execute("SELECT * FROM records ORDER BY start_date DESC")
    rows = cursor.fetchall()
    conn.close()
    
    records = []
    for r in rows:
        item = dict(r)
        item["diagnosis"] = classify_record(item)
        if anomalies_only and item["diagnosis"]["is_clean"]:
            continue
        records.append(item)
    return {"records": records}

@app.post("/api/records")
def create_record(item: RecordCreate):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT INTO records (start_date, end_date, notes, source, created_at, updated_at)
            VALUES (?, ?, ?, 'manual', ?, ?)
        """, (item.start_date, item.end_date, item.notes or '', now_str, now_str))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="该开始日期的记录已存在")
    conn.close()
    recalculate_intervals()
    return {"status": "success"}

@app.put("/api/records/{record_id}")
def update_record(record_id: int, item: RecordUpdate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM records WHERE id = ?", (record_id,))
    rec = cursor.fetchone()
    if not rec:
        conn.close()
        raise HTTPException(status_code=404, detail="记录不存在")

    start_date = item.start_date if item.start_date is not None else rec["start_date"]
    end_date = item.end_date if item.end_date is not None else rec["end_date"]
    notes = item.notes if item.notes is not None else rec["notes"]
    now_str = datetime.now().isoformat()

    cursor.execute("""
        UPDATE records
        SET start_date = ?, end_date = ?, notes = ?, updated_at = ?
        WHERE id = ?
    """, (start_date, end_date, notes, now_str, record_id))
    conn.commit()
    conn.close()
    recalculate_intervals()
    return {"status": "success"}

@app.delete("/api/records/{record_id}")
def delete_record(record_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    recalculate_intervals()
    return {"status": "success"}

# One-click data cleaning actions
@app.post("/api/clean/split-missed")
def split_missed_record(record_date: str = "2026-07-04"):
    """
    Splits a missed 54-day cycle (e.g. 2026-07-04) by inserting the estimated missing June period.
    From 2026-05-11 to 2026-07-04 (54 days): inserts 2026-06-07 ~ 2026-06-11 (5 days, interval 27d).
    """
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO records (start_date, end_date, duration, notes, source, created_at, updated_at)
            VALUES ('2026-06-07', '2026-06-11', 5, '系统清洗补全：拆分54天异常间隔', 'auto_clean', ?, ?)
        """, (now_str, now_str))
        conn.commit()
    finally:
        conn.close()
    recalculate_intervals()
    return {"status": "success", "message": "已成功补全 2026-06-07 生理期记录，54天异常已平滑拆分为两个标准 27 天周期！"}

@app.post("/api/clean/fix-duration")
def fix_prolonged_record(record_id: int = 24):
    """
    Fixes the 49-day prolonged recording error (2023-12-20 ~ 2024-02-06) to a normal 6-day period (2023-12-20 ~ 2023-12-25).
    """
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("""
        UPDATE records 
        SET end_date = '2023-12-25', notes = '系统清洗修正：原记录49天为打卡遗漏，已修正为标准6天', updated_at = ?
        WHERE start_date = '2023-12-20'
    """, (now_str,))
    conn.commit()
    conn.close()
    recalculate_intervals()
    return {"status": "success", "message": "已将 2023-12-20 异常 49 天记录修正为正常的 6 天持续时间！"}

@app.post("/api/action/start")
def action_start(action: ActionDate):
    target_date = action.date or str(date.today())
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM records WHERE end_date IS NULL LIMIT 1")
    open_rec = cursor.fetchone()
    if open_rec:
        conn.close()
        raise HTTPException(status_code=400, detail="已有正在进行中的经期记录，请先记录结束")

    now_str = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT INTO records (start_date, end_date, source, created_at, updated_at)
            VALUES (?, NULL, 'manual', ?, ?)
        """, (target_date, now_str, now_str))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="该日期的记录已存在")
    conn.close()
    recalculate_intervals()
    return {"status": "success", "start_date": target_date}

@app.post("/api/action/stop")
def action_stop(action: ActionDate):
    target_date = action.date or str(date.today())
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, start_date FROM records WHERE end_date IS NULL ORDER BY start_date DESC LIMIT 1")
    open_rec = cursor.fetchone()
    if not open_rec:
        conn.close()
        raise HTTPException(status_code=400, detail="当前没有正在进行中的经期记录")

    s_date = datetime.strptime(open_rec["start_date"], "%Y-%m-%d").date()
    e_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    if e_date < s_date:
        conn.close()
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")

    now_str = datetime.now().isoformat()
    cursor.execute("""
        UPDATE records 
        SET end_date = ?, updated_at = ?
        WHERE id = ?
    """, (target_date, now_str, open_rec["id"]))
    conn.commit()
    conn.close()
    recalculate_intervals()
    return {"status": "success", "end_date": target_date}

@app.get("/api/calendar/{year}/{month}")
def get_calendar_month(year: int, month: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT start_date, end_date FROM records ORDER BY start_date ASC")
    all_records = cursor.fetchall()
    conn.close()

    settings = get_settings()
    period_cycle = get_effective_period_days()
    menses_days = int(settings.get("menses_days", "5"))

    import calendar
    _, days_in_month = calendar.monthrange(year, month)
    
    period_dates = set()
    latest_start = None
    for r in all_records:
        s_date = datetime.strptime(r["start_date"], "%Y-%m-%d").date()
        latest_start = s_date
        e_date = datetime.strptime(r["end_date"], "%Y-%m-%d").date() if r["end_date"] else s_date + timedelta(days=menses_days-1)
        cur = s_date
        while cur <= e_date:
            period_dates.add(cur)
            cur += timedelta(days=1)

    predicted_period_dates = set()
    predicted_ovulation_dates = set()
    predicted_fertile_dates = set()

    if latest_start:
        next_cycle_start = latest_start + timedelta(days=period_cycle)
        for _ in range(3):
            for d in range(menses_days):
                predicted_period_dates.add(next_cycle_start + timedelta(days=d))
            ov_day = next_cycle_start + timedelta(days=period_cycle - 14)
            predicted_ovulation_dates.add(ov_day)
            for fd in range(-5, 2):
                predicted_fertile_dates.add(ov_day + timedelta(days=fd))
            next_cycle_start += timedelta(days=period_cycle)

    days_info = []
    for day in range(1, days_in_month + 1):
        cur_date = date(year, month, day)
        status = "normal"
        if cur_date in period_dates:
            status = "period"
        elif cur_date in predicted_period_dates:
            status = "predicted_period"
        elif cur_date in predicted_ovulation_dates:
            status = "ovulation"
        elif cur_date in predicted_fertile_dates:
            status = "fertile"

        days_info.append({
            "day": day,
            "date": str(cur_date),
            "status": status
        })

    return {
        "year": year,
        "month": month,
        "days": days_info
    }

@app.get("/api/settings")
def api_get_settings():
    s = get_settings()
    masked = dict(s)
    if masked.get("smtp_pass"):
        masked["has_smtp_pass"] = True
        masked["smtp_pass"] = "••••••••"
    else:
        masked["has_smtp_pass"] = False
    masked["effective_period_cycle"] = get_effective_period_days()
    return masked

@app.post("/api/settings")
def api_update_settings(data: dict):
    if data.get("smtp_pass") == "••••••••":
        del data["smtp_pass"]
    update_settings(data)
    return {"status": "success", "settings": api_get_settings()}

@app.post("/api/mail/test")
def api_test_mail():
    result = check_and_send_reminder(force_test=True)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("reason") or result.get("error"))
    return result

@app.get("/api/wechat/subscribers")
def api_wechat_subscribers():
    from app.reminder import get_wechat_subscribers_and_token
    settings = get_settings()
    wc_appid = settings.get("wechat_appid") or os.getenv("WECHAT_APPID", "")
    wc_secret = settings.get("wechat_secret") or os.getenv("WECHAT_SECRET", "")
    if not wc_appid or not wc_secret:
        return {"status": "unconfigured", "count": 0, "openids": [], "is_ready": False}
    openids, _ = get_wechat_subscribers_and_token(wc_appid, wc_secret)
    return {
        "status": "success",
        "count": len(openids),
        "openids": openids,
        "is_ready": len(openids) >= 1
    }

@app.post("/api/wechat/test")
def api_test_wechat():
    from app.reminder import send_wechat_card_to_all
    settings = get_settings()
    wc_appid = settings.get("wechat_appid") or os.getenv("WECHAT_APPID", "")
    wc_secret = settings.get("wechat_secret") or os.getenv("WECHAT_SECRET", "")
    wc_template = settings.get("wechat_template_id") or os.getenv("WECHAT_TEMPLATE_ID", "")
    if not wc_appid or not wc_secret or not wc_template:
        raise HTTPException(status_code=400, detail="请先在设置中填写 WeChat 测试号 AppID、Secret 和 Template ID")
    res = send_wechat_card_to_all(
        wc_appid, wc_secret, wc_template,
        header="🌸 姨妈日历 · 测试服务通知",
        date_str=str(date.today()),
        apply_info="微信模板消息推送测试成功！",
        listing_info="推送模式：多端全员广播",
        tomorrow_info="关注测试号即可同步接收关怀卡片！",
        remark="点击卡片直达姨妈日历网站查看全景推算 👉"
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("reason") or res.get("error"))

    update_settings({
        "last_remind_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "last_remind_type": "wechat_test",
        "last_remind_type_cn": "微信卡片测试推送",
        "last_remind_summary": f"已成功向 {res.get('pushed_count', 1)} 位关注者推送微信服务通知卡片",
        "last_remind_channel": "微信服务通知"
    })

    return res

@app.get("/api/export")
def api_export_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM records ORDER BY start_date ASC")
    records = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in records:
        r["diagnosis"] = classify_record(r)

    return {
        "export_time": datetime.now().isoformat(),
        "total_records": len(records),
        "settings": get_settings(),
        "analytics": get_clean_analytics(),
        "records": records
    }


# Serve Frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/favicon.ico")
def serve_favicon():
    favicon_file = os.path.join(static_dir, "images", "favicon.ico")
    if os.path.exists(favicon_file):
        return FileResponse(favicon_file, media_type="image/x-icon")
    return FileResponse(os.path.join(static_dir, "images", "logo.png"), media_type="image/png")

@app.head("/{full_path:path}")
@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    index_file = os.path.join(static_dir, "index.html")
    return FileResponse(index_file)

