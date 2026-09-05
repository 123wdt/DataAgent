-- ============================================================
-- BizAgent 内置业务库 schema（模拟 46团盐碱地监测平台真实结构）
-- 库: bizagent  |  设计依据: monitor-platform 库真实表结构
-- 说明: region_zone(区域) -> region_patch(地块) / mon_station(站点)
--       站点产生 mon_* 监测记录，越限写入 alert_* 预警
-- ============================================================

DROP TABLE IF EXISTS alert_soil_log;
DROP TABLE IF EXISTS alert_threshold;
DROP TABLE IF EXISTS irri_control;
DROP TABLE IF EXISTS irri_fertilizer_tank;
DROP TABLE IF EXISTS mon_ph_record;
DROP TABLE IF EXISTS mon_groundwater_record;
DROP TABLE IF EXISTS mon_weather_record;
DROP TABLE IF EXISTS mon_soil_record;
DROP TABLE IF EXISTS mon_station;
DROP TABLE IF EXISTS region_patch;
DROP TABLE IF EXISTS region_zone;

-- 区域（北区/南区）
CREATE TABLE region_zone (
    id          bigserial PRIMARY KEY,
    name        varchar(100) NOT NULL,
    level_code  smallint NOT NULL DEFAULT 1,
    area        numeric,
    note        text,
    type        varchar(2) NOT NULL DEFAULT '1',
    create_time timestamp NOT NULL DEFAULT now(),
    update_time timestamp NOT NULL DEFAULT now()
);

-- 地块（1号地块...6号地块，属某区域）
CREATE TABLE region_patch (
    id          bigserial PRIMARY KEY,
    zone_id     bigint NOT NULL REFERENCES region_zone(id),
    name        varchar(100),
    area        numeric,
    level_code  smallint NOT NULL DEFAULT 1,
    note        varchar(255),
    create_time timestamp NOT NULL DEFAULT now(),
    update_time timestamp NOT NULL DEFAULT now()
);

-- 站点（墒情站/气象站/地下水站/pH站）
CREATE TABLE mon_station (
    id          bigserial PRIMARY KEY,
    name        varchar(100) NOT NULL,
    code        varchar(50) NOT NULL,
    station_type varchar(30) NOT NULL,   -- soil / weather / groundwater / ph
    status      varchar(20) NOT NULL DEFAULT 'online',  -- online/offline
    longitude   numeric NOT NULL,
    latitude    numeric NOT NULL,
    zone_id     bigint REFERENCES region_zone(id),
    description varchar(255),
    create_time timestamp NOT NULL DEFAULT now(),
    update_time timestamp NOT NULL DEFAULT now()
);

-- 土壤墒情记录（小时粒度）
CREATE TABLE mon_soil_record (
    id          bigserial PRIMARY KEY,
    station_id  bigint NOT NULL REFERENCES mon_station(id),
    humidity    numeric,      -- 含水量 %
    salinity    numeric,      -- 盐分 g/kg
    record_time timestamp NOT NULL,
    status      varchar(20),
    create_time timestamp NOT NULL DEFAULT now()
);
CREATE INDEX idx_soil_station_time ON mon_soil_record (station_id, record_time);

-- 气象记录（日粒度）
CREATE TABLE mon_weather_record (
    id          bigserial PRIMARY KEY,
    station_id  bigint NOT NULL REFERENCES mon_station(id),
    temperature numeric,
    humidity    integer,
    wind_speed  numeric,
    wind_direction varchar(10),
    rainfall    numeric,
    evaporation numeric,
    sun_hours   numeric,
    record_date date NOT NULL,
    create_time timestamp NOT NULL DEFAULT now()
);
CREATE INDEX idx_weather_station_date ON mon_weather_record (station_id, record_date);

-- 地下水位记录
CREATE TABLE mon_groundwater_record (
    id          bigserial PRIMARY KEY,
    station_name varchar(100) NOT NULL,
    depth       numeric,
    ec          integer,
    temperature numeric,
    record_time timestamp NOT NULL,
    create_time timestamp NOT NULL DEFAULT now(),
    status      smallint NOT NULL DEFAULT 0
);

-- pH 记录
CREATE TABLE mon_ph_record (
    id          bigserial PRIMARY KEY,
    station_id  bigint NOT NULL REFERENCES mon_station(id),
    ph          numeric NOT NULL,
    record_time timestamp NOT NULL,
    create_time timestamp NOT NULL DEFAULT now()
);

-- 预警阈值（对齐真实: 盐分1.0~6.0 / pH 6.0~9.0 / 湿度12~30 / 虫情120）
CREATE TABLE alert_threshold (
    id               bigserial PRIMARY KEY,
    salinity_max     numeric NOT NULL DEFAULT 6.0,
    salinity_min     numeric NOT NULL DEFAULT 1.0,
    ph_max           numeric NOT NULL DEFAULT 9.0,
    ph_min           numeric NOT NULL DEFAULT 6.0,
    humidity_min     numeric NOT NULL DEFAULT 12.0,
    humidity_max     numeric NOT NULL DEFAULT 30.0,
    offline_minutes  integer NOT NULL DEFAULT 30,
    gw_depth_min     numeric NOT NULL DEFAULT 0.5,
    gw_depth_max     numeric NOT NULL DEFAULT 8.0,
    gw_ec_max        integer NOT NULL DEFAULT 6000,
    gw_temp_max      numeric NOT NULL DEFAULT 25.0,
    wq_ec_max        integer NOT NULL DEFAULT 2000,
    wq_ph_max        numeric NOT NULL DEFAULT 8.5,
    wq_turbidity_max numeric NOT NULL DEFAULT 30,
    wq_do_min        numeric NOT NULL DEFAULT 5.0,
    pest_count_max   integer NOT NULL DEFAULT 120,
    update_time      timestamp NOT NULL DEFAULT now(),
    update_by        bigint
);

-- 预警日志（预警/严重 两级）
CREATE TABLE alert_soil_log (
    id          bigserial PRIMARY KEY,
    alert_time  timestamp NOT NULL,
    station_id  bigint NOT NULL REFERENCES mon_station(id),
    point_name  varchar(100) NOT NULL,
    alert_type  varchar(50) NOT NULL,   -- humidity / salinity
    level       varchar(20) NOT NULL,   -- warning / serious
    detail      text NOT NULL,
    status      varchar(20) NOT NULL DEFAULT 'unhandled',  -- unhandled/handled
    handle_time timestamp,
    handle_by   bigint,
    create_time timestamp NOT NULL DEFAULT now()
);
CREATE INDEX idx_alert_station_time ON alert_soil_log (station_id, alert_time);

-- 灌溉控制记录（水肥执行）
CREATE TABLE irri_control (
    id           bigserial PRIMARY KEY,
    zone_id      bigint REFERENCES region_zone(id),
    control_mode varchar(10) NOT NULL,   -- fertigation / irrigation / manual
    water_amount numeric,
    fert_amount  numeric,
    soil_moisture numeric,
    salinity     numeric,
    water_level  numeric,
    ph           numeric,
    pump_status  varchar(10),
    valve_status varchar(10),
    advice       text,
    operate_time timestamp NOT NULL,
    operate_by   bigint,
    create_time  timestamp NOT NULL DEFAULT now()
);

-- 施肥罐
CREATE TABLE irri_fertilizer_tank (
    id           bigserial PRIMARY KEY,
    name         varchar(100) NOT NULL,
    nutrient_type varchar(50) NOT NULL,
    capacity     numeric,
    current_level numeric,
    unit         varchar(10),
    status       varchar(20),
    alert_msg    varchar(255),
    create_time  timestamp NOT NULL DEFAULT now(),
    update_time  timestamp NOT NULL DEFAULT now()
);