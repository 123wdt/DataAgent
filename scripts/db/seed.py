"""
BizAgent 内置业务库造数脚本（模拟 46团盐碱地监测平台真实结构）
用法: python scripts/db/seed.py
连接: 环境变量可覆盖 (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)，默认本机 5433
产出: 2 区域 / 6 地块 / 12 站点 / 90 天监测数据(小时粒度) / 预警日志(与越限联动) / 灌溉记录 / 施肥罐
固定随机种子，可重复执行生成一致数据。
"""
import os
import random
from datetime import datetime, timedelta

import psycopg2

random.seed(20260827)

CONN = dict(
    host=os.environ.get("PGHOST", "localhost"),
    port=int(os.environ.get("PGPORT", "5433")),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgresql"),
    dbname=os.environ.get("PGDATABASE", "bizagent"),
)

# 真实阈值（monitor-platform alert_threshold 实测值）
TH = dict(
    salinity_min=1.0, salinity_max=6.0,
    ph_min=6.0, ph_max=9.0,
    humidity_min=12.0, humidity_max=30.0,
)

def run_sql(cur, sql, rows):
    if rows:
        cur.executemany(sql, rows)

def seed():
    conn = psycopg2.connect(**CONN)
    cur = conn.cursor()
    now = datetime.now()

    # ---- 区域 / 地块 ----
    zones = [("北区", 1), ("南区", 2)]
    zone_ids = {}
    for name, lv in zones:
        cur.execute("insert into region_zone(name, level_code, type, create_time, update_time) values (%s,%s,'1',now(),now()) returning id", (name, lv))
        zone_ids[name] = cur.fetchone()[0]
    patches = [("北区", "1号地块"), ("北区", "2号地块"), ("北区", "3号地块"),
               ("南区", "4号地块"), ("南区", "5号地块"), ("南区", "6号地块")]
    patch_ids = {}
    for zname, pname in patches:
        cur.execute("insert into region_patch(zone_id, name, area, level_code, create_time, update_time) values (%s,%s,%s,1,now(),now()) returning id",
                    (zone_ids[zname], pname, round(random.uniform(150, 400), 1)))
        patch_ids[pname] = cur.fetchone()[0]

    # ---- 站点（墒情站 每地块 1 个 + 气象/地下水/pH 每区 1 个）----
    stations = []  # (name, type, zone)
    for i, pname in enumerate(patches, start=1):
        stations.append((f"{i}号墒情站", "soil", pname[0]))
    for zname, _lv in zones:
        stations.append((f"{zname}气象站", "weather", zname))
        stations.append((f"{zname}地下水站", "groundwater", zname))
        stations.append((f"{zname}pH站", "ph", zname))
    stn_ids, stn_zone = {}, {}
    for name, stype, zname in stations:
        code = f"ST{len(stn_ids)+1:03d}"
        cur.execute(
            "insert into mon_station(name, code, station_type, status, longitude, latitude, zone_id, create_time, update_time) "
            "values (%s,%s,%s,'online',%s,%s,%s,now(),now()) returning id",
            (name, code, stype,
             round(82.5 + random.uniform(-0.2, 0.2), 6),
             round(41.0 + random.uniform(-0.1, 0.1), 6),
             zone_ids[zname]))
        stn_ids[name] = cur.fetchone()[0]
        stn_zone[name] = zname

    # ---- 90 天监测数据（小时粒度，按站点类型）----
    start = now - timedelta(days=90)
    hour_count = 90 * 24
    alerts = []  # (alert_time, station_id, point_name, alert_type, level, detail)
    soil_rows = []
    weather_rows = []
    for name, stype, zname in stations:
        sid = stn_ids[name]
        if stype == "soil":
            # 该站在北区/南区的盐分基线与波动
            base_salt = 2.8 if zname == "北区" else 4.2     # 南区盐分偏高
            trend = random.uniform(-0.3, 0.3)               # 缓慢趋势
            for h in range(hour_count):
                t = start + timedelta(hours=h)
                day_phase = 2.0 * ((h % 24) / 24)           # 日内水分波动
                salt = base_salt + trend * (h / hour_count) + random.uniform(-0.6, 0.6)
                hum = 22.0 + day_phase + random.uniform(-3, 3)
                if zname == "南区" and h > hour_count * 0.7:  # 后期南区盐分持续超标制造预警段
                    salt = min(9.0, salt + 2.8)
                if zname == "北区" and hour_count * 0.75 < h < hour_count * 0.78:  # 北区一段干旱：湿度严重偏低
                    hum = min(hum, 7.0)
                salt = round(max(0.5, salt), 2)
                hum = round(max(8.0, min(38.0, hum)), 2)
                soil_rows.append((sid, hum, salt, t))
                # 越限联动预警（稀疏采样避免刷屏：每 6 小时窗口最多 1 条）
                over = None
                if salt > TH["salinity_max"]:
                    over = ("salinity", "盐分超标", salt)
                elif hum < TH["humidity_min"]:
                    over = ("humidity", "含水量偏低", hum)
                if over and h % 6 == 0:
                    lv = "serious" if (over[2] > TH["salinity_max"] + 1.5 or hum < TH["humidity_min"] - 4) else "warning"
                    alerts.append((t, sid, f"{name}", over[0], lv, f"{over[1]}：当前值 {over[2]}，阈值 {TH[over[0]+'_max' if over[0] in ('salinity','humidity') else '']}"))
        elif stype == "weather":
            for d in range(90):
                date = (start + timedelta(days=d)).date()
                seasonal = 8.0 * (d / 90)  # 入秋降温
                weather_rows.append((sid,
                    round(28.0 - seasonal + random.uniform(-4, 4), 1),      # 温度
                    random.randint(35, 70),                                  # 湿度
                    round(random.uniform(0.5, 5.0), 1),                      # 风速
                    random.choice(["东", "东南", "南", "西南", "西", "西北", "北", "东北"]),
                    round(max(0, random.gauss(1.2, 2.5)), 1),                # 降雨
                    round(random.uniform(2, 6), 1),                          # 蒸发
                    round(random.uniform(4, 9), 1),                          # 日照
                    date))
        elif stype == "groundwater":
            gw_rows = [(name, round(random.uniform(1.5, 6.0), 2), random.randint(1500, 5000),
                        round(random.uniform(12, 18), 1), start + timedelta(days=d*3)) for d in range(30)]
            run_sql(cur, "insert into mon_groundwater_record(station_name, depth, ec, temperature, record_time, create_time, status) values (%s,%s,%s,%s,%s,now(),0)", gw_rows)
        elif stype == "ph":
            ph_rows = [(sid, round(random.uniform(7.0, 8.8), 1), start + timedelta(days=d*2)) for d in range(45)]
            run_sql(cur, "insert into mon_ph_record(station_id, ph, record_time, create_time) values (%s,%s,%s,now())", ph_rows)

    run_sql(cur, "insert into mon_soil_record(station_id, humidity, salinity, record_time, create_time) values (%s,%s,%s,%s,now())", soil_rows)
    run_sql(cur, "insert into mon_weather_record(station_id, temperature, humidity, wind_speed, wind_direction, rainfall, evaporation, sun_hours, record_date, create_time) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())", weather_rows)

    # ---- 预警阈值 + 预警日志 ----
    cur.execute("select count(*) from alert_threshold")
    if cur.fetchone()[0] == 0:
        cur.execute("insert into alert_threshold(salinity_max,salinity_min,ph_max,ph_min,humidity_min,humidity_max,offline_minutes,gw_depth_min,gw_depth_max,gw_ec_max,gw_temp_max,wq_ec_max,wq_ph_max,wq_turbidity_max,wq_do_min,pest_count_max,update_time) "
                    "values (6.0,1.0,9.0,6.0,12.0,30.0,30,0.5,8.0,6000,25.0,2000,8.5,30,5.0,120,now())")
    # 图斑 detail 修正：写入可读详情
    alert_rows = [(a[0], a[1], a[2], a[3], a[4], a[5], random.choice(["unhandled", "handled"])) for a in alerts]
    run_sql(cur, "insert into alert_soil_log(alert_time, station_id, point_name, alert_type, level, detail, status, create_time) values (%s,%s,%s,%s,%s,%s,%s,now())", alert_rows)

    # ---- 灌溉执行记录 + 施肥罐 ----
    irri_rows = []
    for i in range(24):
        zname = random.choice(zones)[0]
        irri_rows.append((zone_ids[zname], random.choice(["fert", "irri", "manual"]),
                          round(random.uniform(10, 40), 1), round(random.uniform(2, 15), 1),
                          round(random.uniform(15, 28), 1), round(random.uniform(1.5, 6.5), 2),
                          random.choice(["on", "off"]), random.choice(["open", "close"]),
                          "根据土壤墒情自动调节灌水量" if random.random() > 0.4 else "建议先冲洗滴灌再施肥",
                          start + timedelta(days=random.randint(0, 89)) + timedelta(hours=random.randint(6, 20))))
    run_sql(cur, "insert into irri_control(zone_id, control_mode, water_amount, fert_amount, soil_moisture, salinity, pump_status, valve_status, advice, operate_time, create_time) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())", irri_rows)
    tanks = [("1号施肥罐", "氮磷钾复合肥", 500, round(random.uniform(120, 460), 1), "L", "normal", None),
             ("2号施肥罐", "有机水溶肥", 300, round(random.uniform(80, 280), 1), "L", "low", "液位偏低，建议补充")]
    run_sql(cur, "insert into irri_fertilizer_tank(name, nutrient_type, capacity, current_level, unit, status, alert_msg, create_time, update_time) values (%s,%s,%s,%s,%s,%s,%s,now(),now())", tanks)

    conn.commit()
    cur.execute("select (select count(*) from mon_station) stn, (select count(*) from mon_soil_record) soil, (select count(*) from mon_weather_record) wth, (select count(*) from alert_soil_log) alert, (select count(*) from irri_control) irri")
    print("造数完成:", cur.fetchone())
    cur.execute("select point_name, alert_type, level, status, detail from alert_soil_log order by alert_time desc limit 5")
    print("预警样例:")
    for r in cur.fetchall():
        print("  ", r)
    conn.close()

if __name__ == "__main__":
    seed()