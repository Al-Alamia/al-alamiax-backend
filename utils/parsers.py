import datetime

def parse_date(date_str,formats:list):
    
    for date_format in formats:
        try:
            return datetime.datetime.strptime(date_str, date_format)
        except ValueError:
            continue
    
    raise ValueError(f"Date format not recognized: {date_str} don't match {' ,'.join(formats)}")

