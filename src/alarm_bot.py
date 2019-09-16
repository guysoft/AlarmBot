#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A telegram bot that manages an alarm clock based on crontab

@author Guy Sheffer (GuySoft) <guysoft at gmail dot com>
"""
from telegram.ext import Updater
from telegram.ext import CommandHandler, CallbackQueryHandler
from telegram.ext import MessageHandler, Filters, ConversationHandler, RegexHandler
from telegram.error import (TelegramError, Unauthorized, BadRequest, 
                            TimedOut, ChatMigrated, NetworkError)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import ReplyKeyboardMarkup
from emoji import emojize
import logging
import traceback
from crontab import CronTab
import signal
from configparser import ConfigParser
from collections import OrderedDict
import os
import json
import random
import string
import sys
from functools import wraps
from urllib.request import urlopen, URLError
import time
import pytz
import subprocess
from database import TelegramUser
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from functools import wraps, partial

debug = 'DEBUG' in os.environ and os.environ['DEBUG'] == "on"

ALARM_COMMAND = os.path.abspath(os.path.join(os.path.dirname(__file__), "alarm.py"))
DIR = os.path.dirname(__file__)


def ensure_dir(d):
    if not os.path.exists(d):
        os.makedirs(d)


def ini_to_dict(path):
    """ Read an ini path in to a dict

    :param path: Path to file
    :return: an OrderedDict of that path ini data
    """
    config = ConfigParser()
    config.read(path)
    return_value=OrderedDict()
    for section in reversed(config.sections()):
        return_value[section]=OrderedDict()
        section_tuples = config.items(section)
        for itemTurple in reversed(section_tuples):
            return_value[section][itemTurple[0]] = itemTurple[1]
    return return_value


def run_command(command, blocking=True):
    p = subprocess.Popen(command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if blocking:
        return [p.stdout.read().decode("utf-8"), p.stderr.read().decode("utf-8")]
    return


def get_timezones():
    return_value = {}
    for tz in pytz.common_timezones:
        c = tz.split("/")
        if len(c) > 1:
            if c[0] not in return_value.keys():
                return_value[c[0]] = []
            return_value[c[0]].append(c[1])

        for i in ["GMT"]:
            if i in return_value.keys():
                return_value.pop(i)

    return return_value


def short_description(job, use_24hour_time_format=True):
    replace_list = [["Sunday", "Sun"],
                    ["Monday", "Mon"],
                    ["Tuesday", "Tue"],
                    ["Wednesday", "Wed"],
                    ["Thursday", "Thr"],
                    ["Friday", "Fri"],
                    ["Saturday", "Sat"],
                    [" through ", "-"],
                    ["At", ""]]

    description = job.description(use_24hour_time_format=use_24hour_time_format)
    for r in replace_list:
        description = description.replace(r[0], r[1])
    return description.strip()


def get_id(existing_ids=[]):
    new_id = ''.join(random.sample((string.ascii_uppercase+string.digits + string.ascii_lowercase),4))
    if new_id in existing_ids:
        return get_id(existing_ids)
    return new_id


def has_access(engine, telegram_id, roles):
    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()
    result = session.query(TelegramUser).filter(TelegramUser.id == telegram_id).first()
    return result.role in roles

def has_user(engine, telegram_id):
    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()
    result = session.query(TelegramUser).filter(TelegramUser.id == telegram_id).count()
    return result == 1


def restricted(func=None, *, roles=["user", "admin"]):
    if func is None:
        return partial(restricted, roles=roles)

    @wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        bot = args[1]
        update = args[2]

        user_id = update.effective_user.id
        if not has_access(self.engine, user_id, roles):
            bot.send_message(chat_id=update.message.chat_id,
                             text="You have no permission to use this command, use web UI to give authorization.",
                             reply_to_message_id=update.message.message_id)
            return
        return func(*args, **kwargs)
    return wrapper




class TelegramCallbackError(Exception):
    def __init__(self, message=""):
        self.message = message


class CronJobsError(Exception):
    def __init__(self, message = ""):
        self.message = message


def build_callback(data):
    return_value = json.dumps(data)
    if len(return_value) > 64:
        raise TelegramCallbackError("Callback data is larger tan 64 bytes")
    return return_value


class CronJobs:
    def __init__(self, cron_id, user=True):
        if " " in cron_id:
            raise CronJobsError("Cron ID must not contain spaces")

        self.cron_id = cron_id
        self.user = user
        self.cron = CronTab(user=user)

    def _create_job(self, command):
        return self.cron.new(command=command, comment=self.cron_id + " " + get_id(self.get_ids()))

    def add_daily(self, command, hour, minute):
        job = self._create_job(command)
        job.hour.on(hour)
        job.minute.on(minute)
        job.enable()
        self.cron.write()
        return
    
    def add_weekday(self, command, hour, minute):
        job = self._create_job(command)
        job.dow.during("SUN", "THU")  # "FRI", "SAT"
        job.hour.on(hour)
        job.minute.on(minute)
        job.enable()
        self.cron.write()
        return

    def job_list(self):
        return_value = []
        for job in self.cron:
            if job.comment.split(" ")[0] == self.cron_id:
                return_value.append(job)
        return_value.sort(key=lambda job: job.schedule().get_next(float))
        return return_value

    def get_readable_jobs(self):
        return_value = []
        for job in self.job_list():
            return_value.append(short_description(job))
        return return_value

    def get_ids(self):
        return_value = []
        for job in self.job_list():
            return_value.append(get_job_id(job))
        return return_value

    def disable(self, job):
        job.enable(False)
        self.cron.write()
        return

    def enable(self, job):
        job.enable(True)
        self.cron.write()
        return

    def remove(self, job):
        self.cron.remove(job)
        self.cron.write()


def get_job_id(job):
    try:
        return job.comment.split(" ")[1]
    except IndexError:
        print(str(traceback.format_exc()))
        return None


def handle_cancel(update):
    query = update.message.text
    if query == "Close" or query == "/cancel":
        reply = "Perhaps another time"
        update.message.reply_text(reply)
        return reply
    return None


def insert_new_user_to_db(engine, telegram_id, name, role="guest"):
    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()
    entry = TelegramUser(id=telegram_id, name=name, role=role)
    session.add(entry)
    session.commit()
    return

class Bot:
    def __init__(self, token, settings):

        self.engine = create_engine(get_uri(settings))

        self.crontab = CronJobs("alarmbot")
        self.selected_alarm_type = ""
        self.selected_continent = ""
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

        self.updater = Updater(token=token)
        self.dispatcher = self.updater.dispatcher
        start_handler = CommandHandler('start', self.start)
        self.dispatcher.add_handler(start_handler)

        self.ALARM_TYPE, self.ALARM_HOUR = range(2)

        self.TIMEZONE_CONTINENT, self.TIMEZONE_TIME = range(2)

        # Add conversation handler with the states ALARM_TYPE, DAILY, WEEKDAY, HOUR
        new_alarm_handler = ConversationHandler(
            entry_points=[CommandHandler('new', self.new_alarm)],
            states={
                self.ALARM_TYPE: [RegexHandler('^(Daily|Weekday Only|Close|/cancel)$', self.alarm_type)],

                self.ALARM_HOUR: [RegexHandler('^([0-2][0-9]:[0-5][0-9]|[0-9]:[0-5][0-9]|/cancel)$', self.hour)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        self.dispatcher.add_handler(new_alarm_handler)

        # Add conversation handler with the states ALARM_TYPE, DAILY, WEEKDAY, HOUR
        set_timezone_handler = ConversationHandler(
            entry_points=[CommandHandler('timezone', self.set_timezone)],
            states={
                self.TIMEZONE_CONTINENT: [RegexHandler('^(' + "|".join(get_timezones().keys()) + '|/cancel)$', self.timezone_continent)],

                self.TIMEZONE_TIME: [RegexHandler('^(.*)$', self.timezone_time)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        self.dispatcher.add_handler(set_timezone_handler)

        stop_handler = CommandHandler('stop', self.stop_alarms)
        self.dispatcher.add_handler(stop_handler)

        help_handler = CommandHandler('help', self.help)
        self.dispatcher.add_handler(help_handler)

        list_handler = CommandHandler('list', self.list_alarms)
        self.dispatcher.add_handler(list_handler)

        time_handler = CommandHandler('time', self.time)
        self.dispatcher.add_handler(time_handler)

        test_handler = CommandHandler('test', self.test)
        self.dispatcher.add_handler(test_handler)

        self.dispatcher.add_handler(CallbackQueryHandler(self.button))

        self.dispatcher.add_error_handler(self.error_callback)

        echo_handler = MessageHandler(Filters.text, self.echo)
        # self.dispatcher.add_handler(echo_handler)

        return
        return

    def start(self, bot, update):
        bot.send_message(chat_id=update.message.chat_id, text="I'm an alarm bot, please type /help for info")
        if not has_user(self.engine, update.message.from_user.id):
            insert_new_user_to_db(self.engine, update.message.from_user.id, update.message.from_user.full_name)
        bot.send_message(chat_id=update.message.chat_id,
                         text="Please add yourself as an admin in the web interface to control the bot")
        return
    
    def new_alarm(self, bot, update):
        keyboard = [[InlineKeyboardButton("Daily"),
                     InlineKeyboardButton("Weekday Only")],
        [InlineKeyboardButton("Close")]]
        
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        
        update.message.reply_text('Select type of alarm, or /cancel to cancel:', reply_markup=reply_markup)
        return self.ALARM_TYPE

    @restricted
    def set_timezone(self, bot, update):
        keyboard = []

        for continent in sorted(get_timezones().keys()):
            keyboard.append([InlineKeyboardButton(continent)])

        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        update.message.reply_text('Please select a continent, or /cancel to cancel:', reply_markup=reply_markup)
        return self.TIMEZONE_CONTINENT

    def timezone_continent(self, bot, update):
        reply = handle_cancel(update)
        if reply is None:
            keyboard = []
            self.selected_continent = update.message.text
            for continent in sorted(get_timezones()[self.selected_continent]):
                keyboard.append([InlineKeyboardButton(continent)])
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            update.message.reply_text('Please select a timezone, or /cancel to cancel:', reply_markup=reply_markup)

            return self.TIMEZONE_TIME
        return ConversationHandler.END

    def timezone_time(self, bot, update):
        reply = handle_cancel(update)
        if reply is None:
            timezone = self.selected_continent + "/" + update.message.text

            timezone_script = os.path.join(DIR, "set_timezone.sh")

            if os.path.isfile(os.path.join("/usr/share/zoneinfo/", timezone)):
                print(run_command(["sudo", timezone_script, timezone]))
                update.message.reply_text(emojize(":clock4: ", use_aliases=True) + 'Timezone set set to: ' + timezone)
            else:
                update.message.reply_text(emojize(":no_entry_sign: ", use_aliases=True) + 'Timezone file does not exist: ' + timezone)

            return ConversationHandler.END
        return ConversationHandler.END

    def alarm_type(self, bot, update):
        query = update.message.text
        reply = "Got illogical reply"

        if query == "Daily" or query == "Weekday Only":
            self.selected_alarm_type = update.message.text
            reply = "Selected daily alarm, type time in format hh:mm, for example: 8:00 or 20:00:"
            update.message.reply_text(reply)
            return self.ALARM_HOUR
        reply = handle_cancel(update)

        update.message.reply_text(reply)
        return ConversationHandler.END
    
    def echo(self, bot, update):
        print(update.message.text)
        bot.send_message(chat_id=update.message.chat_id, text=update.message.text)
        return
    
    def cancel(self, bot, update):
        bot.send_message(chat_id=update.message.chat_id, text="Perhaps another time")
        return
        
    def hour(self, bot, update):
        try:
            data = update.message.text
            if data == "/cancel":
                reply = "Perhaps another time"
            else:

                data = data.split(":")
                hour = int(data[0])
                minute = int(data[1])

                reply = emojize(":alarm_clock:", use_aliases=True) \
                        + " Created " + self.selected_alarm_type + " alarm at: " + str(hour) + ":" + str(minute)

                if self.selected_alarm_type == "Daily":
                    self.crontab.add_daily(ALARM_COMMAND + " " +
                                           os.path.abspath(os.path.join(DIR, "alarm.mp3")), hour, minute)
                else:
                    self.crontab.add_weekday(ALARM_COMMAND + " " +
                                           os.path.abspath(os.path.join(DIR, "alarm.mp3")), hour, minute)

            update.message.reply_text(reply)
        except ValueError as e:
            print("fail")
            print(str(traceback.format_exc()))
            reply = "Error, not valid format"
            update.message.reply_text(reply)
            return self.ALARM_TYPE
        return ConversationHandler.END

    def error_callback(self, bot, update, error):
        try:
            raise error
        except Unauthorized as e:
            # remove update.message.chat_id from conversation list
            pass
        except BadRequest:
            # handle malformed requests - read more below!
            pass
        except TimedOut:
            # handle slow connection problems
            pass
        except NetworkError:
            # handle other connection problems
            pass
        except ChatMigrated as e:
            # the chat_id of a group has changed, use e.new_chat_id instead
            pass
        except TelegramError:
            # handle all other telegram related errors
            pass
        return

    def help(self, bot, update):
        icon = emojize(":information_source: ", use_aliases=True)
        text = icon + " The following commands are available:\n"

        commands = [["/new", "Create new alarm"],
                    ["/list", "List alarms, enable/disable and remove alarms"],
                    ["/stop", "Stop all alarms"],
                    ["/timezone", "Set the timezone (only works if sudo requires no password)"],
                    ["/test", "Play an alarm to test"],
                    ["/time", "Print time and timezone on device"],
                    ["/help", "Get this message"]
                    ]

        for command in commands:
            text += command[0] + " " + command[1] + "\n"

        bot.send_message(chat_id=update.message.chat_id, text=text)

    @restricted
    def time(self, bot, update):
        reply, _ = run_command(["date"])
        bot.send_message(chat_id=update.message.chat_id, text=reply)
        return

    @restricted
    def test(self, bot, update):
        run_command([ALARM_COMMAND, os.path.abspath(os.path.join(DIR, "alarm.mp3"))], False)
        reply = "Testing alarm! Send /stop to stop"
        bot.send_message(chat_id=update.message.chat_id, text=reply)
        return

    @restricted
    def stop_alarms(self, bot, update):
        alarm_folder = os.path.expanduser(os.path.join("~", ".alarmbot"))
        ensure_dir(alarm_folder)
        lock_dir = alarm_folder
        for lock_file in os.listdir(lock_dir):
            try:
                pid = int(lock_file.split(".lock")[0])
                os.kill(pid, signal.SIGINT)
            except (ValueError, ProcessLookupError):
                 pass
        bot.send_message(chat_id=update.message.chat_id, text="Stopping alarm!")
        return

    @restricted
    def list_alarms(self, bot, update):
        keyboard = []

        for i, job in enumerate(self.crontab.job_list()):
            description = short_description(job).split(",")

            icon = emojize(":bell:", use_aliases=True)
            alarm_button = InlineKeyboardButton(icon, callback_data=build_callback(
                {"command": "disable", "alarm": get_job_id(job)}))

            if not job.enabled:
                icon = emojize(":no_bell:", use_aliases=True)
                alarm_button = InlineKeyboardButton(icon, callback_data=build_callback(
                    {"command": "enable","alarm": get_job_id(job)}))

            icon = emojize(":x:", use_aliases=True)
            delete_button = InlineKeyboardButton(icon, callback_data=build_callback(
                    {"command": "remove","alarm": get_job_id(job)}))

            close = build_callback({"command": "close"})
            if len(job) > 1:
                keyboard.append([alarm_button, delete_button,
                                 InlineKeyboardButton(description[0], callback_data=close),
                                 InlineKeyboardButton(", ".join(description[1:]), callback_data=close)])
            else:
                keyboard.append([alarm_button, delete_button,
                                 InlineKeyboardButton(description[0], callback_data=close)])

        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text('Alarm list:', reply_markup=reply_markup)
        return

    def button(self, bot, update):
        query = update.callback_query

        try:
            data = json.loads(query.data)
        except json.JSONDecodeError:
            data = query.data
        reply = "Got message, but not sure how to handle:" + str(data)

        if type(data) == dict and "command" in data:
            if data["command"] == "enable":
                for alarm in self.crontab.job_list():
                    if data["alarm"] == get_job_id(alarm):
                        reply = emojize(":bell:", use_aliases=True) + " Enabling alarm: " + short_description(alarm)
                        self.crontab.enable(alarm)
                        break

            if data["command"] == "disable":
                for alarm in self.crontab.job_list():
                    if data["alarm"] == get_job_id(alarm):
                        reply = emojize(":no_bell:", use_aliases=True) + " Disabling alarm: " + short_description(alarm)
                        self.crontab.disable(alarm)
                        break

            if data["command"] == "remove":
                for alarm in self.crontab.job_list():
                    if data["alarm"] == get_job_id(alarm):
                        reply = "removing alarm: " + short_description(alarm)
                        self.crontab.remove(alarm)

            if data["command"] == "close":
                reply = "Closed"

        bot.edit_message_text(text=reply, chat_id=query.message.chat_id, message_id=query.message.message_id)
        return

    def run(self):
        self.updater.start_polling()
        return


def check_connectivity(reference):
    try:
        urlopen(reference, timeout=1)
        return True
    except URLError:
        return False


def wait_for_internet():
    while not check_connectivity("https://api.telegram.org"):
        print("Waiting for internet")
        time.sleep(1)


def mysql_init_db(uri, settings):
    mysql_engine = create_engine(uri)
    mysql_engine.execute("CREATE DATABASE IF NOT EXISTS {0} ".format(settings["db"]["db_name"]))
    return

if __name__ == "__main__":
    from common import get_config, CONFIG_PATH, get_uri_without_db, get_uri
    from webserver import webserver

    settings = get_config()

    mysql_init_db(get_uri_without_db(settings), settings)
    webserver.init_db(get_uri(settings))

    if not CONFIG_PATH:
        print("Error, no config file")
        sys.exit(1)

    if ("main" not in settings) or ("token" not in settings["main"]):
        print("Error, no token in config file")

    wait_for_internet()

    a = Bot(settings["main"]["token"], settings)
    a.run()
    print("Bot Started")

    webserver.run()
    print("Webserver started")
