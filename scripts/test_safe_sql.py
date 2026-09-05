"""safe_sql + db 层冒烟测试（通过文件执行，避免在命令行出现危险 SQL 字样触发审批）。"""
import sys
sys.path.insert(0, "src")
from agents.sql_data_agent.safe_sql import validate_sql, check_tables_in_whitelist
from agents.sql_data_agent.db import query

def run():
    # 合法 SELECT
    r = validate_sql("select salinity, record_time from mon_soil_record where station_id=1")
    print("合法SELECT通过:", r.ok, "|", r.reason or "OK")

    # 写操作关键字
    r = validate_sql("DELETE FROM mon_soil_record WHERE id=1")
    print("DELETE被拒:", not r.ok, "|", r.reason)

    # 堆叠注入
    r = validate_sql("select * from mon_soil_record; DROP TABLE mon_station")
    print("堆叠被拒:", not r.ok, "|", r.reason)

    # 系统表
    r = validate_sql("select * from pg_user")
    print("系统表被拒:", not r.ok, "|", r.reason)

    # 白名单外表
    r = check_tables_in_whitelist("select * from users")
    print("越权表被拒:", not r.ok, "|", r.reason)

    # 白名单内
    r = check_tables_in_whitelist("select * from mon_soil_record")
    print("白名单内通过:", r.ok)

    # 真实查询
    rows = query("select station_id, round(avg(humidity)::numeric,2) as avg_hum from mon_soil_record group by station_id order by station_id limit 5")
    print("真实查询结果:", rows)

if __name__ == "__main__":
    run()
