#!/usr/bin/env python
# coding: utf-8


from time import sleep
import os
from datetime import datetime, timedelta
import sys
import time


import config


import serial


class Arduino():
   def __init__(self, parent=None):
      super(Arduino, self).__init__()
      print('init Arduino communication')

      try:
        self.serialCOM = serial.Serial('/dev/ttyS0', 115200, timeout=10, write_timeout=1)
        time.sleep(2)
        print(self.serialCOM)
        self.connected = True
      except Exception as ex:
         print(str(ex))

      self.command = ''


   def handleCOM1(self, ser, data):

       tokens = data.split('|')
       print(tokens)
       if(tokens[0] == 'DONE'):
          print('self.doneEmit.emit()')
          self.doneEmit.emit()
       if(tokens[0] == 'P'):
          self.positionEmit.emit(tokens[1])
       if(tokens[0] == 'Ready to Go'):
          self.readyToGoEmit.emit()

   def readFromCOM(self):
      while True:
        try:
          reading = self.serialCOM.readline().decode().strip()
#          print(reading)
          if(len(reading) > 0):
            return reading
        except Exception as ex:
          print(str(ex))

        time.sleep(0.1)


   def send(self, command):

#     print('cmd {}'.format(command))
     self.command = command + '\n'
     self.serialCOM.write(command.encode())                #transmit data serially 
     self.serialCOM.flush()



if __name__ == '__main__':

  try:

    config = config.Configuration()
    config.getConfig()
    print(config.calibration)
    comm = Arduino()

    print('Be sure KneeSpa app is not running.')
    input('Clear all weight/pressure - Press Enter when ready.')

    while True:
      comm.send("L1")
      data = comm.readFromCOM()

      tokens = data.split('|')
      if(tokens[0] == 'step 1'):
        break

    while True:
      response = input('Enter weight.')
      weight = float(response)
      comm.send("L2{:.2f}".format(weight))
      data = comm.readFromCOM()

      tokens = data.split('|')
      if(tokens[0] == 'step 2'):
        break

    while True:
      response = input('Calibration Complete.')
      comm.send("L3")
      data = comm.readFromCOM()

      tokens = data.split('|')
      print(tokens)
      if(len(tokens) > 1):
        config.calibration = float(tokens[1])
        config.updateConfig()
      if(tokens[0] == 'step 3'):
#        print('self.doneEmit.emit()')
        break

  except KeyboardInterrupt:
    print('Ctrl/C')
  except Exception as e:
    print(str(e))
