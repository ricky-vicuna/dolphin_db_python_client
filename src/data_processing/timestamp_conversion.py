from datetime import date, datetime, time, timezone 
from multiprocessing import Value
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def parse_sse_datetime(event_time:int, 
                          trading_date:date, 
                          source_tz:ZoneInfo = SHANGHAI_TZ,
                          ) -> datetime:
    '''
    SSE Tick Trade Event 
    The event time only show HHMMSScc version 
    For instance 
    14302506 → 14:30:25.060
     9420311 → 09:42:03.110 
    
    output: 
        2026
    ''' 
    if len(str(event_time)) < 7 or len(str(event_time)) > 8:
        raise ValueError(f"The event_time is mal-format {event_time} ")
    
    text = str(event_time).zfill(8)
    hour = int(text[0:2])
    minute = int(text[2:4])
    second = int(text[4:6])
    centisecond = int(text[6:8])
    local_time = time(
        hour=hour,
        minute=minute,
        second=second,
        microsecond=centisecond * 10_000,
    )

    return datetime.combine(
        trading_date,
        local_time,
        tzinfo=source_tz,
    )

def parse_szse_datetime(event_time: int, source_tz = SHANGHAI_TZ) -> datetime:

    text = str(event_time)
    
    year = int(text[0:4])
    month = int(text[4:6])
    day = int(text[6:8])
    hour = int(text[8:10])
    minute = int(text[10:12])
    second = int(text[12:14])
    
    # 最後兩位是小數部分（假設是厘秒 cc，即 0.01 秒）
    # 轉成 microsecond (乘以 10,000)
    millisecond = int(text[14:17]) if len(text) >= 17 else 0
    microsecond = millisecond * 1_000
 

    return datetime(
        year=year,
        month=month,
        day=day,
        hour=hour,
        minute=minute,
        second=second,
        microsecond=microsecond,
        tzinfo=source_tz
    )



def parse_recv_datetime(time_str:str) ->datetime: 
    return datetime.fromisoformat(time_str).replace(tzinfo=SHANGHAI_TZ)



def convert_dt_to_nano_utc_ts(dt:datetime) -> int: 
    return int(dt.timestamp() * 1_000_000_000)


if __name__ == "__main__": 
    example_sse_event_time:int = 9420311
    example_szse_event_time:int = 2026102809420390
    today_date = date.today()

    sse_dt = parse_sse_datetime(example_sse_event_time,today_date)
    szse_dt = parse_szse_datetime(example_szse_event_time)
    print(f"SSE datetime {sse_dt} \nSSE ts: {convert_dt_to_nano_utc_ts(sse_dt)}")
    print(f"SZSE datetime {szse_dt} \nSZSE ts: {convert_dt_to_nano_utc_ts(szse_dt)}")

    
