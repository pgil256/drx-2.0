# -*- coding: utf-8 -*-
"""

@author: grimesr
"""
from datetime import datetime
import time
import threading

import atexit

from PyQt5 import QtCore
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt5.QtCore import pyqtSlot

ACTUATOR = 12


class WorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        tuple (exctype, value, traceback.format_exc() )

    result
        object data returned from processing, anything

    progress
        int indicating % progress

    '''
    finished = pyqtSignal(bool)
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(str)
    APressure = pyqtSignal(str)
    pressureComplete = pyqtSignal()

'''
     degrees vs distance
      0 0" extended (will hold here and return)
      5 5" extended (will hold here and return)
     10 4" extended (will hold here and return)
     15 3"
     20 2"
     25 1"
     30 Full retract
'''

NOWEIGHT = 0
STARTWEIGHT =  5
TENLBS = 10
STARTPOSITION = 0.5

class KeepPressure(QtCore.QRunnable):
   def __init__(self, pressure, parent=None):
     super(KeepPressure, self).__init__()

     self.pressure = pressure

     self.running = False

   @pyqtSlot()
   def run(self):
     print("Pressure Thread start")
     self.running = True

   def stop(self):
     print('Pressure stop')
     self.running = False

     self.setToPressure(self.pressure)

   def setToPressure(self, desiredPressure):

     while self.running:
       command = 'P{}\n'.format(desiredPressure)
       self.arduino.write(command)                #transmit data serially 
       print('cmd {}'.format(command.strip()))

       time.sleep(0.5)

     print('end')

class Protocols(QtCore.QRunnable):
   progress = pyqtSignal(str)
   completed = pyqtSignal()

   protocol = ''
   pressure = 0
   cycles = 0

   protocolList = ['S', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'A0']
   def __init__(self, _AFactor, protocol, pressure, cycles, ser, parent=None):
#     QThread.__init__(self, parent)
     super(Protocols, self).__init__()

     self.arduino = ser

     self.AFactor = _AFactor

     self.signals = WorkerSignals()

     self.isRunning = False

     self.I2Cstatus = 0

     self.protocol = protocol
     self.pressure = pressure
     self.cycles = cycles
     self.startPosition = 0
     self.position = 0

     print(self.protocol, self.protocolList)
     if(self.protocol not in self.protocolList):
        return

     self.isRunning = False
     self.exitFlag = threading.Event()


   @pyqtSlot()
   def run(self):
#     print("Thread start")

     self.isRunning = True

     if(self.protocol[0] == 'S'):
       print('setup')
       self.setup()

     if(self.protocol[0] == 'A'):
       self.AProtocol(self.protocol, self.pressure, self.cycles)
#     print('thread END')
#     self.completed.emit()
#     self.signals.finished.emit(True)  # Done

   def stop(self):
     print('stop')
     self.isRunning = False
     self.exitFlag.set()

     try:
       self.arduino.send('X')                #transmit data serially 
     except Exception as e:
       print(str(e))

   def AProtocol(self, protocol, pressure, cycles):
     print('*** {} pressure {} cycles {}'.format(protocol, pressure, cycles))

     print('sendCalibration')
     self.arduino.send('L1')
#     time.sleep(0.5)
     self.I2Cstatus = 0
     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('stopped')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')

     if(self.setAToDistance(STARTPOSITION) == False):
        self.signals.finished.emit(False)
        return
     self.signals.progress.emit('Moved to start {}'.format(STARTPOSITION))
     time.sleep(0.5)

     if(protocol == 'A0'):
        self.protocol0(pressure)
     if(protocol == 'A1'):
        self.protocol1(pressure, cycles)
     if(protocol == 'A2'):
        self.protocol2(pressure, cycles)
     if(protocol == 'A3'):
        self.protocol3(pressure, cycles)
     if(protocol == 'A4'):
        self.protocol4(pressure, cycles)
     if(protocol == 'A5'):
        self.protocol5(pressure, cycles)
     if(protocol == 'A6'):
        self.protocol6(pressure, cycles)
     if(protocol == 'A7'):
        self.protocol7(pressure, cycles)
     if(protocol == 'A8'):
        self.protocol8(pressure, cycles)


   def killProtocol(self):
     self.isRunning = False

   def setup(self):
     inches = self.degreeList[DEGREES10] #set as initial angle
     position = int(inches * self.AFactor / 6.0)


   def pressureDone(self):
     self.stopPressure = True
     print('self.stopPressure = True')

   def I2CStatus(self):
     self.I2Cstatus = True

   def setToPressure(self, desiredPressure):
     command = 'P{}'.format(desiredPressure)
     self.arduino.send(command)                #transmit data serially 
     print('cmd {}'.format(command.strip()))

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('stopped')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def setAToDistance(self, inches):
     print(' positioned to deg {} in.'.format(inches))

     command = 'A12{}'.format(inches)
     self.arduino.send(command)

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('STOPPED')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def setToDistance(self, position):
     inches = (position  * 8.0)/ self.AFactor
     print(' positioned to {}  {} in.'.format(position, inches))

     command = 'A12{}'.format(position)
     self.arduino.send(command)
     print('cmd {}'.format(command.strip()))

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('STOPPED')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def jerk(self, option):
     print(' jerking.')

     command = 'J{}'.format(option)
     self.arduino.send(command)
     print('cmd {}'.format(command.strip()))

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('STOPPED')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def resetA(self):
     self.signals.progress.emit('>>Moved to start {}'.format(NOWEIGHT))
     if(self.setAToDistance(NOWEIGHT) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Moved to start {}'.format(NOWEIGHT))
     return True


   def status(self, positionA, positionB, steps, pressure):
 #    print('>> A {} B {} C {} Pressure {}'.format(positionA, positionB, steps, pressure))
#     self.startPosition = positionA
     self.pressure = pressure
     self.signals.APressure.emit('Pressure at {} lbs'.format(self.pressure))

   def getPosition(self):
     self.I2Cstatus = 0
#     command = 'G{}'.format(ACTUATOR)
     command = 'S'
     self.arduino.send(command)                #transmit data serially 
     print('cmd {}'.format(command.strip()))

     while(self.I2Cstatus == 0):
       if(not self.isRunning):
          self.arduino.send('X')                #transmit data serially 
          print('stopped')
          return False

       time.sleep(0.1)
     self.I2Cstatus = 0
     print('end')
     return True

   def resetA(self):
     self.signals.progress.emit('>>Moved to start {}'.format(NOWEIGHT))
     if(self.setAToDistance(NOWEIGHT) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Moved to start {}'.format(NOWEIGHT))
     return True

   def protocol0(self, pressure):
     self.getPosition()
     inches = (self.startPosition  * 6.0)/ self.AFactor
     print('A Position {} Pressure {} lbs {:.2f} inches'.format(self.startPosition, self.pressure, inches))

     self.signals.progress.emit('A Positioned at {:.1f} in. for start.'.format(inches))
     self.signals.finished.emit(True)


   def protocol1(self, pressure, cycles):

     currentPressure = TENLBS
     for cycle in range(1, cycles+1):

       for push in range(currentPressure, pressure+1, 3):
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, push))
         if(self.setToPressure(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, push))
         self.exitFlag.wait(timeout=5)

       self.signals.progress.emit('>>Moved to start.')
       if(self.setToDistance(self.startPosition) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Moved to start.')

     if(self.resetA()):
       self.signals.finished.emit(True)


   def protocol2(self, pressure, cycles):

     for cycle in range(1, cycles+1):

       self.signals.progress.emit('>>Moved to start.')
       if(self.setToDistance(self.startPosition) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Moved to start.')

       currentPressure = TENLBS
       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       while(currentPressure <= pressure):
         currentPressure -= 1
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         last = False
         if(currentPressure + 3 > pressure):
            currentPressure = pressure
            last = True
         else:
            currentPressure += 3

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         if(last):
           break

       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 10 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=10)

     if(self.resetA()):
       self.signals.finished.emit(True)

   def protocol3(self, pressure, cycles):

     for cycle in range(1, cycles+1):

       currentPressure = TENLBS
       for push in range(currentPressure, pressure+1, 5):
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, push))
         if(self.setToPressure(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, push))
         self.exitFlag.wait(timeout=5)

       self.exitFlag.wait(timeout=5)

     if(self.resetA()):
       self.signals.finished.emit(True)

   def protocol4(self, pressure, cycles):

     for cycle in range(1, cycles+1):

       self.signals.progress.emit('>>Moved to start.')
       if(self.setToDistance(self.startPosition) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Moved to start.')

       currentPressure = TENLBS
       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=5)

       while(currentPressure < pressure):
         currentPressure -= 1
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         last = False
         if(currentPressure + 5 > pressure):
            currentPressure = pressure
            last = True
         else:
            currentPressure += 5

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)

         if(last):
           break

       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 10 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=10)

     if(self.resetA()):
       self.signals.finished.emit(True)


   def protocol5(self, pressure, cycles):

     currentPressure = pressure
     for cycle in range(1, cycles+1):

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 60 secs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 60 secs'.format(cycle, currentPressure))
       self.exitFlag.wait(timeout=60)

     if(self.resetA()):
       self.signals.finished.emit(True)

   def protocol6(self, pressure, cycles):

     self.signals.progress.emit('>>Moved to start.')
     if(self.setToDistance(self.startPosition) == False):
        self.signals.finished.emit(False)
        return
     self.signals.progress.emit('Moved to start.')

     self.signals.progress.emit('>>Pressure {} lbs hold 5 secs'.format(TENLBS))
     if(self.setToPressure(TENLBS) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure {} lbs hold 5 secs'.format(TENLBS))
     self.exitFlag.wait(timeout=5)

     for cycle in range(1, cycles+1):

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 60 secs'.format(cycle, pressure))
       if(self.setToPressure(pressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 60 secs'.format(cycle, pressure))
       self.exitFlag.wait(timeout=60)

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, TENLBS))
       if(self.setToPressure(TENLBS) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, TENLBS))
       self.exitFlag.wait(timeout=5)

     if(self.resetA()):
       self.signals.finished.emit(True)

   def protocol7(self, pressure, cycles):

     currentPressure = TENLBS
     for cycle in range(1, cycles+1):

       for push in range(currentPressure, pressure+1, 5):
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs'.format(cycle, push))
         if(self.setToPressure(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs'.format(cycle, push))

         self.jerk('')
         self.exitFlag.wait(timeout=6)

#       self.jerk('S')


     if(self.resetA()):
       self.signals.finished.emit(True)

   def protocol8(self, pressure, cycles):

     currentPressure = pressure
     for cycle in range(1, cycles+1):

       self.signals.progress.emit('>>Cycle {} Pressure {} lbs'.format(cycle, currentPressure))
       if(self.setToPressure(currentPressure) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure {} lbs'.format(cycle, currentPressure))

       for i in range(10):
         self.jerk('')
         self.exitFlag.wait(timeout=3)

#       self.jerk('S')

     if(self.resetA()):
       self.signals.finished.emit(True)

   def setI2CStatus(self, channel):
      self.I2Cstatus = 1
      print('self.I2Cstatus = 1')

