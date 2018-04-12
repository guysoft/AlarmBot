#!/usr/bin/env bash
sudo apt-get update
sudo apt-get install -y python3-pip ffmpeg libavcodec-extra python3-pyaudio python3-mysql.connector
sudo pip3 install -r requirements.txt
