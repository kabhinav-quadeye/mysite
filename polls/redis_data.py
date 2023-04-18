import datetime
import pytz
import json
import logging

logging.basicConfig(filename='errors.log', level=logging.ERROR)

def get_from_redis(redis_key):
    redis_value = ''
    try:
        if isinstance(redis_value, bytes):
            redis_value = redis_value.decode('utf-8')
    except Exception as e:
        logging.error('Error decoding bytes: ' + str(e))
    return redis_value

def get_jsoned_object(redis_key):
    try:
        json_value = get_from_redis(redis_key)
        if json_value:
            return json.loads(json_value)
        else:
            return {}
    except Exception as e:
        logging.error("Error in getting " + redis_key + ": " + str(e))
        return {}


def get_user_holiday_redis():
    today = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).date()
    return get_jsoned_object('today_holiday_users_{}'.format(today))
