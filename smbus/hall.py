#!/usr/bin/python
#--------------------------------------
#    ___  ___  _ ____
#   / _ \/ _ \(_) __/__  __ __
#  / , _/ ___/ /\ \/ _ \/ // /
# /_/|_/_/  /_/___/ .__/\_, /
#                /_/   /___/
#
#       Hall Effect Sensor
#
# This script tests the sensor on GPIO17.
#
# Author : Matt Hawkins
# Date   : 08/05/2018
#
# https://www.raspberrypi-spy.co.uk/
#
#--------------------------------------

# Import required libraries
import time
import datetime
import RPi.GPIO as GPIO

EXTRAFORWARD = 17
EXTRABACKWARD = 27


position = 0

def forwardExtraBtnClicked():
        GPIO.output(EXTRABACKWARD, GPIO.LOW)
        GPIO.output(EXTRAFORWARD, GPIO.HIGH)

def reverseExtraBtnClicked():
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.HIGH)

def resetExtraBtnClicked():
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)

def sensorCallback(channel):
  global position
  # Called if sensor output changes
  timestamp = time.time()
  stamp = datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
  if GPIO.input(channel):
    # No magnet
    position += 1
    print("Sensor {} HIGH {} {}".format(channel, position, stamp))
  else:
    # Magnet
    print("Sensor {} LOW {}".format(channel, stamp))

def main():
  # Wrap main content in a try block so we can
  # catch the user pressing CTRL-C and run the
  # GPIO cleanup function. This will also prevent
  # the user seeing lots of unnecessary error
  # messages.

  # Get initial reading
  sensorCallback(4)

  forwardExtraBtnClicked()
  time.sleep(15)
  try:
    # Loop until users quits with CTRL-C
    while True :

      print('Out')
      reverseExtraBtnClicked()
      time.sleep(20)

      print('In')

      forwardExtraBtnClicked()
      time.sleep(20)

      print('Stopped')
      resetExtraBtnClicked()
      time.sleep(2)

  except KeyboardInterrupt:
    # Reset GPIO settings
    GPIO.cleanup()

# Tell GPIO library to use GPIO references
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

print("Setup GPIO pin as input on GPIO4")

GPIO.setup(EXTRAFORWARD, GPIO.OUT)
GPIO.setup(EXTRABACKWARD, GPIO.OUT)

# Set Switch GPIO as input
# Pull high by default
GPIO.setup(4 , GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.add_event_detect(4, GPIO.RISING, callback=sensorCallback, bouncetime=50)
#GPIO.setup(17 , GPIO.IN, pull_up_down=GPIO.PUD_UP)
#GPIO.add_event_detect(17, GPIO.RISING, callback=sensorCallback, bouncetime=50)

if __name__=="__main__":
  try:
    main()
  except Exception as e:
    print(str(e))
    reverseExtraBtnClicked()
    time.sleep(5)
    GPIO.cleanup()           # clean up GPIO on normal exit
