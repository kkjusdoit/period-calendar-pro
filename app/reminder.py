import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email.header import Header
from datetime import datetime, date, timedelta
import logging
import urllib.request
import json

from app.database import get_db, get_settings, update_settings, get_effective_period_days

logger = logging.getLogger("reminder")

def get_wechat_subscribers_and_token(appid: str, secret: str):
    """Fetch all openids that have scanned/subscribed to the WeChat sandbox test account."""
    try:
        token_url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
        req = urllib.request.urlopen(token_url, timeout=10)
        token_res = json.loads(req.read().decode("utf-8"))
        access_token = token_res.get("access_token")
        if not access_token:
            logger.error(f"Failed to get WeChat access token: {token_res}")
            return [], None
        
        user_url = f"https://api.weixin.qq.com/cgi-bin/user/get?access_token={access_token}"
        req = urllib.request.urlopen(user_url, timeout=10)
        user_res = json.loads(req.read().decode("utf-8"))
        openids = user_res.get("data", {}).get("openid", [])
        return openids, access_token
    except Exception as e:
        logger.error(f"Error fetching WeChat subscribers: {e}")
        return [], None

def send_wechat_card_to_all(appid: str, secret: str, template_id: str, header: str, date_str: str, apply_info: str, listing_info: str, tomorrow_info: str, remark: str, target_url: str = None):
    """
    Broadcasts native WeChat template card to ALL subscribed users (husband + wife once she scans QR code).
    """
    if not target_url:
        target_url = os.getenv("APP_URL", "http://localhost:3600")
    try:
        openids, access_token = get_wechat_subscribers_and_token(appid, secret)
        if not access_token:
            return {"status": "error", "reason": "Failed to obtain WeChat access token"}
        if not openids:
            return {"status": "skipped", "reason": "No subscribed WeChat users found"}
        
        send_url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"
        results = []
        for openid in openids:
            payload = {
                "touser": openid,
                "template_id": template_id,
                "url": target_url,
                "data": {
                    "header": {"value": header, "color": "#e91e63"},
                    "first": {"value": header, "color": "#e91e63"},
                    "date": {"value": date_str, "color": "#1e293b"},
                    "status": {"value": apply_info, "color": "#e11d48"},
                    "cycle": {"value": listing_info, "color": "#475569"},
                    "tips": {"value": tomorrow_info, "color": "#059669"},
                    "apply_info": {"value": apply_info, "color": "#e11d48"},
                    "listing_info": {"value": listing_info, "color": "#475569"},
                    "tomorrow_info": {"value": tomorrow_info, "color": "#059669"},
                    "remark": {"value": remark, "color": "#6366f1"}
                }
            }
            req = urllib.request.Request(send_url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            res = urllib.request.urlopen(req, timeout=10)
            res_data = json.loads(res.read().decode("utf-8"))
            results.append({"openid": openid, "result": res_data})
            logger.info(f"WeChat card pushed to {openid}: {res_data}")
        return {"status": "success", "pushed_count": len(results), "details": results}
    except Exception as e:
        logger.error(f"Error sending WeChat template cards: {e}")
        return {"status": "error", "error": str(e)}

def send_smtp_email(host: str, port: int, user: str, password: str, to_addrs, subject: str, html_body: str):
    """Send an email via SMTP (supporting SSL on 465 and TLS on 587/25) to one or multiple recipients."""
    if isinstance(to_addrs, str):
        recipients = [addr.strip() for addr in to_addrs.replace(";", ",").split(",") if addr.strip()]
    else:
        recipients = list(to_addrs)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("姨妈日历", "utf-8")), user))
    msg["To"] = ", ".join(recipients)

    part = MIMEText(html_body, "html", "utf-8")
    msg.attach(part)

    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        server.starttls()

    server.login(user, password)
    server.sendmail(user, recipients, msg.as_string())
    server.quit()

def check_and_send_reminder(force_test=False):
    """
    Check period status and send email reminders:
    1. Upcoming period reminder: e.g. 3 days before expected start.
    2. Period ended reminder: when period is active and expected duration elapsed (to avoid forgetting to record end date).
    """
    settings = get_settings()
    
    if not force_test and settings.get("email_enabled") != "1":
        return {"status": "skipped", "reason": "Email reminder disabled in settings"}
        
    smtp_host = settings.get("smtp_host", "smtp.qq.com")
    smtp_port = int(settings.get("smtp_port", "465"))
    smtp_user = settings.get("smtp_user", "").strip()
    smtp_pass = settings.get("smtp_pass", "").strip()
    email_to = settings.get("email_to", "").strip()
    remind_days = int(settings.get("remind_days_before", "3"))
    remind_end_enabled = settings.get("remind_end_enabled", "1") == "1"
    partner_name = settings.get("partner_name", "老婆")
    last_reminded = settings.get("last_reminded_cycle", "")
    last_reminded_end = settings.get("last_reminded_end_cycle", "")

    if not smtp_user or not smtp_pass or not email_to:
        return {"status": "error", "reason": "SMTP credentials or recipient email missing"}

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT start_date, end_date FROM records ORDER BY start_date DESC LIMIT 1")
    latest = cursor.fetchone()
    conn.close()

    if not latest and not force_test:
        return {"status": "skipped", "reason": "No menstrual records found"}

    today = date.today()
    period_cycle = get_effective_period_days()
    menses_days = int(settings.get("menses_days", "5"))

    remind_time = settings.get("remind_time", "08:00")
    if not force_test:
        target_hour = int(remind_time.split(":")[0]) if ":" in remind_time else 8
        current_hour = datetime.now().hour
        if current_hour != target_hour:
            return {
                "status": "skipped",
                "reason": f"Current hour ({current_hour}:00) not matching configured remind_time ({remind_time})",
                "current_hour": current_hour,
                "target_hour": target_hour
            }

    wechat_enabled = settings.get("wechat_enabled", "1") == "1"
    wc_appid = settings.get("wechat_appid") or os.getenv("WECHAT_APPID", "")
    wc_secret = settings.get("wechat_secret") or os.getenv("WECHAT_SECRET", "")
    wc_template = settings.get("wechat_template_id") or os.getenv("WECHAT_TEMPLATE_ID", "")
    app_url = os.getenv("APP_URL", "http://localhost:3600")

    # CASE 1: Test Notification (Email + WeChat)
    if force_test:
        subject = "🧪 [测试成功] 双通道提醒服务已就绪·来潮前3天早8点提醒"
        preheader = "【状态就绪】已绑定邮箱与微信服务通知。推送时机：①来潮前3天早08:00发关怀备忘；②行经满5天早08:00提醒打卡。点击直达网站。"
        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #fff5f8; border-radius: 16px; padding: 24px; border: 1px solid #f8bbd0; color: #333;">
          <!-- Hidden Preheader for notification preview -->
          <span style="display:none !important; visibility:hidden; mso-hide:all; font-size:1px; line-height:1px; max-height:0; max-width:0; opacity:0; overflow:hidden;">
            {preheader}
          </span>

          <div style="text-align: center; margin-bottom: 16px;">
            <span style="font-size: 36px;">🌸</span>
            <h2 style="color: #e91e63; margin: 8px 0 0; font-size: 20px;">姨妈日历 · 测试服务通知</h2>
          </div>

          <!-- High-Signal Summary Box (Instantly visible without scrolling) -->
          <div style="background: #ffffff; border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1.5px solid #f43f5e; box-shadow: 0 4px 12px rgba(244, 63, 94, 0.08);">
            <div style="font-size: 15px; font-weight: bold; color: #e11d48; margin-bottom: 6px;">
              ✅ 邮箱与微信卡片推送均已就绪
            </div>
            <div style="font-size: 13px; color: #334155; line-height: 1.6;">
              已同时关联 <b>{email_to}</b>。<br>
              微信模板卡片支持全员广播，爱人扫码关注测试号即可同享接收。
            </div>
          </div>
          
          <div style="background: #ffffff; border-radius: 12px; padding: 16px; margin: 16px 0; border: 1px solid #fce4ec;">
            <div style="color: #ad1457; font-weight: bold; font-size: 14px; margin-bottom: 8px;">
              ⏰ 自动化推送时机与规则：
            </div>
            <ul style="color: #616161; font-size: 13px; line-height: 1.8; margin: 0; padding-left: 20px;">
              <li><b>经期快来提醒</b>：预计来潮前 <b>{remind_days} 天上午 {remind_time}</b> 自动发送温馨备忘与关怀贴士</li>
              <li><b>经期结束打卡提醒</b>：行经满 <b>{menses_days} 天次日上午 {remind_time}</b> 自动提醒打卡记录结束时间</li>
              <li><b>双通道实时送达</b>：QQ 邮箱摘要通知 + 微信原生服务通知卡片</li>
            </ul>
          </div>

          <div style="text-align: center; margin-top: 22px;">
            <a href="{app_url}" target="_blank" style="background: #f06292; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 30px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(240, 98, 146, 0.35);">
              👉 点击打开「姨妈日历」网站
            </a>
          </div>

          <div style="text-align: center; color: #9e9e9e; font-size: 12px; margin-top: 20px; border-top: 1px dashed #f8bbd0; padding-top: 12px;">
            网址: <a href="{app_url}" style="color: #e91e63;">{app_url}</a> · 贴心守护每一天
          </div>
        </div>
        """
        email_res = None
        try:
            send_smtp_email(smtp_host, smtp_port, smtp_user, smtp_pass, email_to, subject, html_content)
            logger.info(f"Test email successfully sent to {email_to}")
            email_res = {"status": "success", "to": email_to}
        except Exception as e:
            logger.error(f"Failed to send test email: {e}")
            email_res = {"status": "error", "error": str(e)}

        wc_res = None
        if wechat_enabled:
            wc_res = send_wechat_card_to_all(
                wc_appid, wc_secret, wc_template,
                header="🧪 服务通知测试成功（全员广播就绪）",
                date_str=str(today),
                apply_info="接收对象：双QQ邮箱 + 双方微信",
                listing_info=f"来潮提醒：提前 {remind_days} 天早 {remind_time} 准时推送",
                tomorrow_info=f"离潮提醒：行经满 {menses_days} 天早 {remind_time} 提醒打卡",
                remark="点击卡片直达姨妈日历网页 👉"
            )

        update_settings({
            "last_remind_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_remind_type": "test",
            "last_remind_type_cn": "双端测试服务通知",
            "last_remind_summary": "测试通知已就绪，已同时送达双 QQ 邮箱与微信关注者",
            "last_remind_channel": "双 QQ 邮箱 + 微信服务通知"
        })

        return {"status": "success", "email": email_res, "wechat": wc_res}

    # CASE 2: Period Ended Reminder ("姨妈走了，以防别忘了统计")
    if latest and latest["end_date"] is None:
        last_start = datetime.strptime(latest["start_date"], "%Y-%m-%d").date()
        # If today >= last_start + menses_days, period is presumed ended
        if remind_end_enabled and today >= (last_start + timedelta(days=menses_days)):
            if last_reminded_end != str(last_start):
                subject = f"💖 姨妈推算已走(满{menses_days}天)·请打卡记录结束日期"
                preheader = f"【结束打卡】{partner_name}本次生理期自{last_start.strftime('%m月%d日')}起满{menses_days}天已顺利结束。请点击直达日历记录离开日期，确保后续推算精准。"
                html_content = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #fff5f8; border-radius: 16px; padding: 24px; border: 1px solid #f8bbd0; color: #333;">
                  <!-- Hidden Preheader for notification preview -->
                  <span style="display:none !important; visibility:hidden; mso-hide:all; font-size:1px; line-height:1px; max-height:0; max-width:0; opacity:0; overflow:hidden;">
                    {preheader}
                  </span>

                  <div style="text-align: center; margin-bottom: 16px;">
                    <span style="font-size: 36px;">💖</span>
                    <h2 style="color: #e91e63; margin: 8px 0 0; font-size: 20px;">姨妈日历 · 结束打卡提醒</h2>
                  </div>

                  <!-- High-Signal Summary Box -->
                  <div style="background: #ffffff; border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1.5px solid #f43f5e; box-shadow: 0 4px 12px rgba(244, 63, 94, 0.08);">
                    <div style="font-size: 15px; font-weight: bold; color: #e11d48; margin-bottom: 6px;">
                      ⏰ 本次经期已满 {menses_days} 天，大姨妈推算已顺利离开
                    </div>
                    <div style="font-size: 13px; color: #334155; line-height: 1.6;">
                      本次行经始于 <b>{last_start.strftime("%m月%d日")}</b>。请及时打卡记录大姨妈离开的具体日期，避免遗漏统计，保证后续周期推算精准！
                    </div>
                  </div>

                  <div style="text-align: center; margin-top: 22px;">
                    <a href="{app_url}" target="_blank" style="background: #f06292; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 30px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(240, 98, 146, 0.35);">
                      👉 打开「姨妈日历」一键打卡
                    </a>
                  </div>

                  <div style="text-align: center; color: #9e9e9e; font-size: 12px; margin-top: 20px; border-top: 1px dashed #f8bbd0; padding-top: 12px;">
                    网址: <a href="{app_url}" style="color: #e91e63;">{app_url}</a> · 贴心守护每一天
                  </div>
                </div>
                """
                try:
                    send_smtp_email(smtp_host, smtp_port, smtp_user, smtp_pass, email_to, subject, html_content)
                    if wechat_enabled:
                        send_wechat_card_to_all(
                            wc_appid, wc_secret, wc_template,
                            header=f"💖 姨妈推算已走(满{menses_days}天)·请打卡记录",
                            date_str=str(today),
                            apply_info=f"行经推算已达 {menses_days} 天，大姨妈应该走啦",
                            listing_info=f"开始日期：{last_start.strftime('%m月%d日')} · 状态：待记录结束时间",
                            tomorrow_info="及时打卡能保证后续周期与排卵推算更精准",
                            remark="点击卡片一键直达网站完成打卡 👉"
                        )
                    update_settings({
                        "last_reminded_end_cycle": str(last_start),
                        "last_remind_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "last_remind_type": "ended",
                        "last_remind_type_cn": "经期结束打卡提醒",
                        "last_remind_summary": f"行经推算已满 {menses_days} 天，提醒记录大姨妈离开日期",
                        "last_remind_channel": "双 QQ 邮箱 + 微信服务通知"
                    })
                    logger.info(f"Period ended reminder successfully sent to {email_to}")
                    return {"status": "success", "type": "ended", "to": email_to, "subject": subject}
                except Exception as e:
                    logger.error(f"Failed to send ended reminder: {e}")
                    return {"status": "error", "error": str(e)}
        return {"status": "skipped", "reason": "Period active but not yet reached threshold or already reminded"}

    # CASE 3: Upcoming Period Reminder ("姨妈快来了")
    if latest:
        last_start = datetime.strptime(latest["start_date"], "%Y-%m-%d").date()
        next_start = last_start + timedelta(days=period_cycle)
        days_left = (next_start - today).days

        if days_left == remind_days:
            if last_reminded != str(next_start):
                subject = f"🌸 还有{days_left}天来潮({next_start.strftime('%m月%d日')})·备好温水暖宝贴"
                preheader = f"【经期备忘】预计{next_start.strftime('%m月%d日')}来潮(倒计时{days_left}天)。备忘：卫生棉/热姜茶/暖宝贴，经前情绪敏感多加包容宠爱。点击直达日历。"
                html_content = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #fff5f8; border-radius: 16px; padding: 24px; border: 1px solid #f8bbd0; color: #333;">
                  <!-- Hidden Preheader for notification preview -->
                  <span style="display:none !important; visibility:hidden; mso-hide:all; font-size:1px; line-height:1px; max-height:0; max-width:0; opacity:0; overflow:hidden;">
                    {preheader}
                  </span>

                  <div style="text-align: center; margin-bottom: 16px;">
                    <span style="font-size: 36px;">🌸</span>
                    <h2 style="color: #e91e63; margin: 8px 0 0; font-size: 20px;">姨妈日历 · 温馨来潮提醒</h2>
                  </div>

                  <!-- High-Signal Summary Box -->
                  <div style="background: #ffffff; border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1.5px solid #f43f5e; box-shadow: 0 4px 12px rgba(244, 63, 94, 0.08);">
                    <div style="font-size: 15px; font-weight: bold; color: #e11d48; margin-bottom: 6px;">
                      预计 {partner_name} 生理期还有 {days_left} 天来临（{next_start.strftime("%m月%d日")}）
                    </div>
                    <div style="font-size: 13px; color: #334155; line-height: 1.6;">
                      基准周期平均 <b>{period_cycle}</b> 天。<br>
                      <b>关怀备忘</b>：常温热饮、卫生棉与暖宝宝；经期前情绪容易敏感疲倦，多一份理解与宠爱 ✨
                    </div>
                  </div>

                  <div style="text-align: center; margin-top: 22px;">
                    <a href="{app_url}" target="_blank" style="background: #f06292; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 30px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(240, 98, 146, 0.35);">
                      👉 打开「姨妈日历」网页
                    </a>
                  </div>

                  <div style="text-align: center; color: #9e9e9e; font-size: 12px; margin-top: 20px; border-top: 1px dashed #f8bbd0; padding-top: 12px;">
                    网址: <a href="{app_url}" style="color: #e91e63;">{app_url}</a> · 贴心守护每一天
                  </div>
                </div>
                """
                try:
                    send_smtp_email(smtp_host, smtp_port, smtp_user, smtp_pass, email_to, subject, html_content)
                    if wechat_enabled:
                        send_wechat_card_to_all(
                            wc_appid, wc_secret, wc_template,
                            header=f"🌸 还有{days_left}天来潮({next_start.strftime('%m月%d日')})",
                            date_str=str(today),
                            apply_info=f"预计来潮：{next_start.strftime('%m月%d日')}（倒计时 {days_left} 天）",
                            listing_info="关怀建议：常温热饮、备好暖宝贴与卫生棉",
                            tomorrow_info="经前情绪易敏感疲倦，多一份理解与宠爱 ✨",
                            remark="点击卡片直达姨妈日历网页查看全景推算 👉"
                        )
                    update_settings({
                        "last_reminded_cycle": str(next_start),
                        "last_remind_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "last_remind_type": "upcoming",
                        "last_remind_type_cn": "经期来临前温馨提醒",
                        "last_remind_summary": f"预计还剩 {days_left} 天（{next_start.strftime('%m月%d日')}）来潮，已发送关怀备忘",
                        "last_remind_channel": "双 QQ 邮箱 + 微信服务通知"
                    })
                    logger.info(f"Upcoming period reminder successfully sent to {email_to}")
                    return {"status": "success", "type": "upcoming", "to": email_to, "subject": subject}
                except Exception as e:
                    logger.error(f"Failed to send upcoming reminder: {e}")
                    return {"status": "error", "error": str(e)}

        return {
            "status": "skipped",
            "reason": f"Days left ({days_left}) not matching threshold ({remind_days}) or already reminded",
            "days_left": days_left,
            "next_start": str(next_start)
        }
    return {"status": "skipped", "reason": "No records"}

def calculate_next_remind(latest, period_cycle: int, menses_days: int, settings: dict, today: date = None):
    """
    Computes the upcoming scheduled reminder time, countdown, event type, and details.
    """
    if today is None:
        today = date.today()

    remind_days = int(settings.get("remind_days_before", "3"))
    remind_time = settings.get("remind_time", "08:00")
    remind_end_enabled = settings.get("remind_end_enabled", "1") == "1"
    partner_name = settings.get("partner_name", "老婆")
    wechat_enabled = settings.get("wechat_enabled", "1") == "1"
    channel = "微信服务通知 + QQ邮箱" if wechat_enabled else "QQ邮箱"

    if not latest:
        return {
            "time_display": "暂无记录",
            "type_cn": "首次打卡后自动推算",
            "summary": "添加第一条生理期记录后，系统将自动预约推送时机。",
            "channel": channel,
            "days_left": None,
            "scheduled_date": None
        }

    last_start = datetime.strptime(latest["start_date"], "%Y-%m-%d").date()
    end_date = latest.get("end_date")

    # CASE A: Currently in period (end_date is None or empty)
    if not end_date:
        expected_end_date = last_start + timedelta(days=menses_days)
        days_diff = (expected_end_date - today).days

        if days_diff > 0:
            return {
                "time_display": f"{expected_end_date.strftime('%m月%d日')} {remind_time} (还有 {days_diff} 天)",
                "type_cn": "经期结束打卡提醒",
                "summary": f"推算行经满 {menses_days} 天（{expected_end_date.strftime('%m月%d日')}），将在早 {remind_time} 自动推送提醒，记录离开日期防漏记。",
                "channel": channel,
                "days_left": days_diff,
                "scheduled_date": str(expected_end_date)
            }
        elif days_diff == 0:
            return {
                "time_display": f"今天 {remind_time} (行经第 {menses_days} 天)",
                "type_cn": "经期结束打卡提醒",
                "summary": f"今日行经已满 {menses_days} 天，早 {remind_time} 自动推送打卡提醒，请留意大姨妈是否已离开。",
                "channel": channel,
                "days_left": 0,
                "scheduled_date": str(expected_end_date)
            }
        else:
            in_days = (today - last_start).days + 1
            return {
                "time_display": f"行经第 {in_days} 天 (待打卡)",
                "type_cn": "等待记录经期结束",
                "summary": f"已超过平均持续天数（{menses_days} 天），大姨妈离开后请点击上方按钮记录结束打卡。",
                "channel": channel,
                "days_left": 0,
                "scheduled_date": str(today)
            }

    # CASE B: Period finished, awaiting next cycle
    next_start = last_start + timedelta(days=period_cycle)
    remind_date = next_start - timedelta(days=remind_days)
    days_to_remind = (remind_date - today).days
    days_to_next = (next_start - today).days

    if days_to_remind > 0:
        return {
            "time_display": f"{remind_date.strftime('%m月%d日')} {remind_time} (还有 {days_to_remind} 天)",
            "type_cn": f"来潮前 {remind_days} 天关怀备忘",
            "summary": f"预计 {next_start.strftime('%m月%d日')} 来潮。将在前 {remind_days} 天（{remind_date.strftime('%m月%d日')}）早 {remind_time} 自动推送微信与邮箱，提醒备齐用品与温水暖宝。",
            "channel": channel,
            "days_left": days_to_remind,
            "scheduled_date": str(remind_date)
        }
    elif days_to_remind == 0:
        return {
            "time_display": f"今天 {remind_time} (倒计时 {remind_days} 天)",
            "type_cn": f"来潮前 {remind_days} 天关怀备忘",
            "summary": f"已到达提前 {remind_days} 天节点，将在今日 {remind_time} 自动向双方微信与邮箱发送关怀通知。",
            "channel": channel,
            "days_left": 0,
            "scheduled_date": str(remind_date)
        }
    elif days_to_next > 0:
        return {
            "time_display": f"{next_start.strftime('%m月%d日')} {remind_time} (还有 {days_to_next} 天来潮)",
            "type_cn": "即将进入经期",
            "summary": f"已进入经前期（还剩 {days_to_next} 天），请注意腹部保暖与作息，大姨妈到达后随时打卡。",
            "channel": channel,
            "days_left": days_to_next,
            "scheduled_date": str(next_start)
        }
    elif days_to_next == 0:
        return {
            "time_display": f"今天预计来潮 (还剩 0 天)",
            "type_cn": "预计今日来潮提醒",
            "summary": f"今天是预计的生理期第一天（周期第 {period_cycle} 天），若见红请点击上方按钮记录来潮。",
            "channel": channel,
            "days_left": 0,
            "scheduled_date": str(next_start)
        }
    else:
        overdue = abs(days_to_next)
        return {
            "time_display": f"已推迟 {overdue} 天",
            "type_cn": "生理期推迟关注",
            "summary": f"已超过预计来潮日 {overdue} 天，请保持放松与规律作息，大姨妈到达后随时打卡。",
            "channel": channel,
            "days_left": 0,
            "scheduled_date": str(today)
        }

