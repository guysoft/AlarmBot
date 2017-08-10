#!/usr/bin/env bash
TIMEZOME=$1
rm /etc/localtime
ln -s /usr/share/zoneinfo/${TIMEZOME} /etc/localtime

