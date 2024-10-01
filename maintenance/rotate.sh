#!/bin/sh

cd /home/pi/kneespa

logrotate  --state ./status -v -f dailyrotate.conf


