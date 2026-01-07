import requests , datetime
import threading

TELEGRAM_BOT_URL = "https://api.telegram.org/bot6723126261:AAH6vOX6pE1xchOHO0y-Id8aSpwMU-LTnew/sendMessage"


def sendTMessage(msg:str,id:int):
    params = {
        'chat_id': id ,#1077637654
        'text': f"{msg}\n{datetime.datetime.now().strftime('%Y-%m-%d & %H:%M:%S')}\n" ,
    }
    return requests.get(TELEGRAM_BOT_URL,params=params)