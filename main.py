import json
import os
import smtplib
import time
from collections import defaultdict
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


def read_caches_from_file():
    try:
        with open(LOG_FILE, "r") as file:
            cache_data = json.load(file)
            return [Cache.from_dict(cache) for cache in cache_data]
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        print(f"Error reading JSON file: {e}")
        return []
    except TypeError as e:
        print(f"Error processing log data: {e}")
        return []


def write_caches_to_file(caches):
    with open(LOG_FILE, "w") as file:
        json.dump([cache.to_dict() for cache in caches], file, indent=2)


def get_emoji(type: pycaching.log.Type) -> str:
    if type == pycaching.log.Type.didnt_find_it:
        return "❌"
    elif type == pycaching.log.Type.needs_maintenance:
        return "🔧"
    elif type == pycaching.log.Type.needs_archive:
        return "🗑️"
    elif type == pycaching.log.Type.found_it:
        return "✅"
    elif type == pycaching.log.Type.owner_maintenance:
        return "🔨"
    elif type == pycaching.log.Type.temp_disable_listing:
        return "🛑"
    elif type == pycaching.log.Type.enable_listing:
        return "🟢"
    elif type == pycaching.log.Type.note:
        return "📝"
    else:
        print(f"Unknown log type: {type}")
        return "❓"


class Log:
    def __init__(self, author: str, type: pycaching.log.Type, date, id: str):
        self.author = author
        self.type = type
        self.date = date
        self.id = id

    def __str__(self):
        formatted_date = self.date.strftime("%d.%m.%Y") if isinstance(self.date, datetime) else self.date
        return f"Status {get_emoji(self.type)} {self.author} am {formatted_date}"

    def to_dict(self):
        return {
            "author": self.author,
            "type": self.type.value,
            "date": str(self.date),
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, dict):
            return cls(
                author=data["author"],
                type=pycaching.log.Type(data["type"]),
                date=data["date"],
                id=data["id"],
            )
        else:
            raise TypeError("Data must be a dictionary")


class Cache:
    def __init__(
        self,
        wp: str,
        name: str,
        not_found_logs: list[Log] = [],
        new_logs: bool = False,
        last_ten_logs_status: list[pycaching.log.Type] = [],
    ):
        self.wp = wp
        self.name = name
        self.not_found_logs = not_found_logs
        self.new_logs = new_logs
        self.last_ten_logs_status = last_ten_logs_status

    def to_dict(self):
        return {
            "wp": self.wp,
            "name": self.name,
            "not_found_logs": [log.to_dict() for log in self.not_found_logs],
        }

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, dict):
            return cls(
                wp=data["wp"],
                name=data["name"],
                not_found_logs=[Log.from_dict(log_data) for log_data in data["not_found_logs"]],
            )
        else:
            raise TypeError("Data must be a dictionary")


def get_my_caches():
    geocaching = pycaching.login()
    return geocaching.advanced_search(options={"hb": "betzebuwe"}, limit=100)


def fetch_last_10_logs(cache):
    logbook = cache.load_logbook(limit=10)
    return logbook


def count_logs_between(logs):
    found_log_index = None
    for i, log in enumerate(logs):
        if log.type == pycaching.log.Type.found_it or log.type == pycaching.log.Type.owner_maintenance:
            found_log_index = i
            break
    if found_log_index is not None:
        return found_log_index
    return len(logs)


def main():
    print("Welchen Modus möchtest du starten?")
    print("1. Alle Caches einmalig anzeigen")
    print(
        "2. [Im konfigurierten Intervall (z.B. 3 Tage)] Nur Caches, die in den letzten 30 Tagen nicht gefunden wurden"
    )
    mode = input("Zahl eingeben (1 oder 2): ")

    if mode == "1":
        caches = []
    elif mode == "2":
        caches = [
            cache
            for cache in read_caches_from_file()
            if any(
                datetime.strptime(log.date, "%Y-%m-%d") > datetime.now() - timedelta(days=30)
                for log in cache.not_found_logs
            )
        ]
    else:
        print("Ungültige Eingabe")
        return

    while mode == "2":
        last30days = datetime.now() - timedelta(days=30)
        print("Checking for new logs")
        caches_of_last_mail = caches.copy()
        my_caches = get_my_caches()
        updates_found = False

        for cache in my_caches:
            print("Checking cache", cache)
            logbook = fetch_last_10_logs(cache)
            new_logs = []
            last_10_logs = []
            for log in logbook:
                last_10_logs.append(log.type)
                if (
                    log.type == pycaching.log.Type.didnt_find_it
                    or log.type == pycaching.log.Type.needs_maintenance
                    or log.type == pycaching.log.Type.needs_archive
                    or log.type == pycaching.log.Type.temp_disable_listing
                ) and log.visited > last30days.date():
                    if log.uuid not in [
                        log.id for cache in caches_of_last_mail for log in cache.not_found_logs
                    ] and not any(log_type == pycaching.log.Type.owner_maintenance for log_type in last_10_logs):
                        new_logs.append(
                            Log(
                                author=log.author,
                                type=log.type,
                                date=log.visited,
                                id=log.uuid,
                            )
                        )
            if new_logs:
                updates_found = True
                for existing_cache in caches:
                    if existing_cache.wp == cache.wp:
                        existing_cache.not_found_logs.extend(new_logs)
                        existing_cache.last_ten_logs_status = last_10_logs
                        existing_cache.last_log_date = datetime.now().date()
                        existing_cache.new_logs = True
                        break
                else:
                    caches.append(
                        Cache(
                            wp=cache.wp,
                            name=cache.name,
                            not_found_logs=new_logs,
                            new_logs=True,
                            last_ten_logs_status=last_10_logs,
                        )
                    )
            else:
                for existing_cache in caches:
                    if existing_cache.wp == cache.wp:
                        existing_cache.last_ten_logs_status = last_10_logs

        if updates_found:
            send_mail(caches, caches_of_last_mail)

        write_caches_to_file(caches)

        print(f"Sleeping for {int(os.getenv('SLEEP_TIME')) / 3600} hours")
        time.sleep(int(os.getenv("SLEEP_TIME", 3600 * 24 * 3)))

    if mode == "1":
        my_caches = get_my_caches()
        for cache in my_caches:
            print("Checking cache", cache)
            logbook = fetch_last_10_logs(cache)
            caches.append(
                Cache(
                    wp=cache.wp,
                    name=cache.name,
                    last_ten_logs_status=[log.type for log in logbook],
                )
            )

        caches.sort(key=lambda cache: cache.name)

        send_mail(caches, [])

        print("Finished")


def send_mail(caches, caches_of_last_mail):
    with smtplib.SMTP(host="smtp.gmail.com", port=587) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(os.getenv("GMAIL_EMAIL"), os.getenv("GMAIL_PW"))
        subject = "Neuer Cache, der nicht gefunden wurde oder Wartung benötigt"
        body = f"""Es gibt neue Logs, die nicht gefunden wurden oder Wartung benötigen:\n\n
        {'\n'.join([str(log) for cache in caches for log in cache.not_found_logs if cache not in caches_of_last_mail])}
        {len(caches_of_last_mail) == 0 and '\nBisherige Logs:'}
        {'\n'.join([str(log) for cache in caches_of_last_mail for log in cache.not_found_logs])}
        """

        body_html = generate_html_body(caches, caches_of_last_mail)

        msg_new = MIMEMultipart("alternative")
        msg_new["Subject"] = subject

        msg_new.attach(MIMEText(body, "plain"))
        msg_new.attach(MIMEText(body_html, "html"))

        server.sendmail(os.getenv("GMAIL_EMAIL"), os.getenv("EMAIL_RECEIVER"), msg_new.as_string())
        print("Email has been sent")


def generate_html_body(caches: list[Cache], caches_of_last_mail):
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
        <div>
    """

    if caches:
        for cache in caches:
            log_emojis = [get_emoji(log) for log in cache.last_ten_logs_status]
            html_str += f"<h3 style='margin-top: 10px; margin-bottom: 5px;'>{"🆕" if cache.new_logs else ""} {cache.name} <a href='https://www.geocaching.com/geocache/{cache.wp}'>Zum Cache</a></h3> <div style='margin-top: 0; margin-bottom: 5px' >Letzte 10 Logs: {' '.join(log_emojis)}</div>"
            for log in cache.not_found_logs:
                formatted_date = format_date(log.date)
                html_str += f'<div class="log-entry">- {log.author} am {formatted_date}: {get_emoji(log.type)} {log.type.name}</div>'
            html_str += "<hr>"
        html_str += f"<div> Legende: {get_emoji(pycaching.log.Type.found_it)} Gefunden | {get_emoji(pycaching.log.Type.didnt_find_it)} Nicht gefunden | {get_emoji(pycaching.log.Type.needs_maintenance)} Wartung benötigt | {get_emoji(pycaching.log.Type.owner_maintenance)} Wartung erfolgt | {get_emoji(pycaching.log.Type.needs_archive)} Archivierung benötigt | {get_emoji(pycaching.log.Type.temp_disable_listing)} Listing deaktiviert | {get_emoji(pycaching.log.Type.enable_listing)} Listing aktiviert | {get_emoji(pycaching.log.Type.note)} Notiz</div>"

    html_str += """
        </div>
    </body>
    </html>
    """
    return html_str


main()
