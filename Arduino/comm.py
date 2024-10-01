#!/usr/bin/env python
# coding: utf-8

from PyQt5.QtCore import QThread, QObject, pyqtSignal, pyqtSlot

from time import sleep
import os
from datetime import datetime, timedelta
import sys
import time
import serial

class Arduino(QObject):
   finished = pyqtSignal()
   progress = pyqtSignal(int)
   doneEmit = pyqtSignal()
   pressureEmit = pyqtSignal(str)
   readyToGoEmit = pyqtSignal()
   positionEmit = pyqtSignal(int, int, str, int)
   statusEmit = pyqtSignal(int, int, int, float)
   AstatusEmit = pyqtSignal(int, int, int, float)
   intReady = pyqtSignal(int)
   displayWeightEmit = pyqtSignal(str)


   @pyqtSlot()
   def procCounter(self): # A slot takes no params
        for i in range(1, 10):
            time.sleep(0.1)
            self.intReady.emit(i)

        self.doneEmit.emit()


   @pyqtSlot()
   def run(self):

      print('startSerial')

      try:
        self.serialCOM = serial.Serial('/dev/ttyS0', 115200, timeout=10, write_timeout=1)
        time.sleep(2)
        print(self.serialCOM)
        self.connected = True
      except Exception as ex:
         print(str(ex))

      print('Inited')

      self.command = ''

      self.readFromCOM(self.serialCOM)

   def handleCOM(self, ser, data):

       s =  0
       tokens = data.split('|')
       if(tokens[0] == 'DONE'):
 #         print('self.doneEmit.emit()')
          print(tokens)
          self.doneEmit.emit()
          s = 1
       if(tokens[0] == 'P'):
          self.positionEmit.emit(tokens[1])
       if(tokens[0] == 'PR'):
          self.pressureEmit.emit(tokens[1])
       if(tokens[0] == 'E'):
          self.positionEmit.emit(int(tokens[1]), int(tokens[2]) , tokens[3], int(tokens[4]))
       if(tokens[0] == 'S'):
          self.statusEmit.emit(int(tokens[1]), int(tokens[2]) , int(tokens[3]), float(tokens[4]))
       if(tokens[0] == 'A'):
          self.AstatusEmit.emit(int(tokens[1]), int(tokens[2]) , int(tokens[3]), float(tokens[4]))
       if(tokens[0] == 'Ready to Go'):
          print('self.readyToGoEmit.emit()')
          self.readyToGoEmit.emit()
       if(tokens[0] == 'weight'):
          self.displayWeightEmit.emit(tokens[1])
       return s

   def readFromCOM(self, ser):
      global startRun
      while True:
        try:
          reading = ser.readline().decode().strip()
#          print(reading)
          if(len(reading) > 0):
            s = self.handleCOM(ser, reading)

        except Exception as ex:
          print(str(ex))

        time.sleep(0.1)


   def send(self, command):

     self.command = command + '\n'
     print('cmd {}'.format(command.strip()))
     self.serialCOM.write(command.encode())                #transmit data serially 
     self.serialCOM.flush()
#     self.doneEmit.emit()


