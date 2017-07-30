AlarmBot
========

A telegram bot that serves as an alarm clock, runs best on a RaspberryPi


Requirements
~~~~~~~~~~~~
* Python3 (and pip probably)
* `python-telegram-bot <https://github.com/python-telegram-bot/python-telegram-bot>`_ (7.0.1+)
* `pyaudio <https://people.csail.mit.edu/hubert/pyaudio>`_
* `pydub <https://github.com/jiaaro/pydub>`_
* `python-crontab <https://github.com/doctormo/python-crontab>`_
* `cron-descriptor <https://github.com/Salamek/cron-descriptor>`_
* `croniter <https://github.com/kiorky/croniter>`_
* `emoji <https://github.com/carpedm20/emoji>`_

How to use it?
--------------

1. Install the requirements, in ubuntu::

    sudo ./src/install_deps.sh
    
or::

    sudo apt-get install -y python3-pip ffmpeg libavcodec-extra python3-pyaudio
    sudo pip3 install -r src/requirements.txt

2. Set copy config.ini.example to config ini and add there your bot's token. You can get a bot token by sending ``/newbot`` to `@BotFather <https://telegram.me/BotFather>`_

3. Run::

    src/alarm_bot.py
    
4. Message ``/start`` to your bot to set up alarms.

Set up service on startup
-------------------------
Run ``src/add_startup_service.sh`` either as the user you want the service to be run as, or ``src/add_startup_service.sh <user to run script>``


Attribution
~~~~~~~~~~~

alarm.mp3 is by `TheZero <https://freesound.org/people/TheZero/sounds/273540/>`_ under CC 1.0


Code contributions are loved!
