import json
import os
import smtplib
import time
from datetime import date
from datetime import datetime
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pycaching
import pycaching.log
from dotenv import load_dotenv


load_dotenv()

LOG_FILE = "logs.json"


def format_date(date_obj):
    if isinstance(date_obj, (datetime, date)):
        return date_obj.strftime("%d.%m.%Y")
    return date_obj


def read_logs_from_file():
    try:
        with open(LOG_FILE, "r") as file:
            logs_data = json.load(file)
            return [Log.from_dict(log) for log in logs_data]
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        print(f"Error reading JSON file: {e}")
        return []
    except TypeError as e:
        print(f"Error processing log data: {e}")
        return []


def write_logs_to_file(logs):
    with open(LOG_FILE, "w") as file:
        json.dump([log.to_dict() for log in logs], file, indent=2)


def get_emoji(type: str) -> str:
    if type == pycaching.log.Type.didnt_find_it:
        return "❌"
    elif type == pycaching.log.Type.needs_maintenance:
        return "🔧"
    elif type == pycaching.log.Type.needs_archive:
        return "🗑️"
    else:
        return "❓"


class Log:
    def __init__(self, author: str, type: str, cache: str, date, id: str, cache_name: str):
        self.author = author
        self.type = type
        self.cache = cache
        self.date = date
        self.id = id
        self.cache_name = cache_name

    def __str__(self):
        formatted_date = self.date.strftime("%d.%m.%Y") if isinstance(self.date, datetime) else self.date
        return f"Status {get_emoji(self.type)} {self.cache_name}: {self.author} am {formatted_date} geloggt: https://www.geocaching.com/geocache/{self.cache.wp}"

    def to_dict(self):
        return {
            "author": self.author,
            "type": str(self.type),
            "cache": str(self.cache),
            "date": str(self.date),
            "id": self.id,
            "cache_name": self.cache_name,
        }

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, dict):
            return cls(
                author=data["author"],
                type=data["type"],
                cache=data["cache"],
                date=data["date"],
                id=data["id"],
                cache_name=data["cache_name"],
            )
        else:
            raise TypeError("Data must be a dictionary")


def get_logs():
    geocaching = pycaching.login()
    return geocaching.advanced_search(options={"hb": "betzebuwe"}, limit=100)


def main():
    logs = read_logs_from_file()
    logs = [log for log in logs if log.date > datetime.now() - timedelta(days=30)]  # Remove logs older than 30 days
    last30days = datetime.now() - timedelta(days=30)
    while True:
        print("Checking for new logs")
        logs_of_last_mail = logs.copy()
        my_caches = get_logs()
        for cache in my_caches:
            print("Checking cache", cache)
            logbook = cache.load_logbook(limit=2)
            for log in logbook:
                if (
                    log.type == pycaching.log.Type.didnt_find_it
                    or log.type == pycaching.log.Type.needs_maintenance
                    or log.type == pycaching.log.Type.needs_archive
                ) and log.visited > last30days.date():
                    if log.uuid not in [log.id for log in logs_of_last_mail]:
                        logs.append(
                            Log(
                                author=log.author,
                                type=log.type,
                                cache=cache,
                                cache_name=cache.name,
                                date=log.visited,
                                id=log.uuid,
                            )
                        )

        if logs_of_last_mail != logs:
            send_mail(logs, logs_of_last_mail)

        write_logs_to_file(logs)

        print("Sleeping for 1 hour")
        time.sleep(3600)


def send_mail(logs, logs_of_last_mail):
    with smtplib.SMTP(host="smtp.gmail.com", port=587) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(os.getenv("GMAIL_EMAIL"), os.getenv("GMAIL_PW"))
        subject = "Neuer Cache, der nicht gefunden wurde oder Wartung benötigt"
        body = f"""Es gibt neue Logs, die nicht gefunden wurden oder Wartung benötigen:\n\n
        {'\n'.join([str(log) for log in logs if log not in logs_of_last_mail])}
        {len(logs_of_last_mail) == 0 and '\nBisherige Logs:'}
        {'\n'.join([str(log) for log in logs_of_last_mail])}
        """

        body_html = generate_html_body(logs, logs_of_last_mail)

        msg_new = MIMEMultipart("alternative")
        msg_new["Subject"] = subject

        msg_new.attach(MIMEText(body, "plain"))
        msg_new.attach(MIMEText(body_html, "html"))

        server.sendmail(os.getenv("GMAIL_EMAIL"), os.getenv("EMAIL_RECEIVER"), msg_new.as_string())
        print("Email has been sent")


def generate_html_body(logs, logs_of_last_mail):
    new_logs = [log for log in logs if log not in logs_of_last_mail]
    previous_logs = logs_of_last_mail if len(logs_of_last_mail) > 0 else []

    html_str = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; }
            .log-entry { margin-bottom: 10px; }
            .log-entry strong { color: #333; }
        </style>
    </head>
    <body>
        <h2>Es gibt Caches, die nicht gefunden wurden oder Wartung benötigen!</h2>
        <div>
    """

    if new_logs:
        html_str += "<h3>Neue Logs:</h3>"
        for log in new_logs:
            formatted_date = format_date(log.date)
            html_str += f'<div class="log-entry"><strong>{log.cache_name}</strong>: {get_emoji(log.type)} {log.author} am {formatted_date}: <a href="https://www.geocaching.com/geocache/{log.cache.wp}">Zum Cache</a></div>'

    if previous_logs:
        html_str += "<h3>Bisherige Logs:</h3>"
        for log in previous_logs:
            formatted_date = format_date(log.date)
            html_str += f'<div class="log-entry"><strong>{log.cache_name}</strong>: {log.type} {log.author} am {formatted_date}: <a href="https://www.geocaching.com/geocache/{log.cache.wp}">Zum Cache</a></div>'

    html_str += """
        </div>
    </body>
    </html>
    """
    return html_str


main()
