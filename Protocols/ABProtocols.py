# -*- coding: utf-8 -*-
"""

@author: grimesr
"""
from datetime import datetime
import time
import threading


from PyQt5 import QtCore
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt5.QtCore import pyqtSlot

DEGREES0 = 0
DEGREES5 = 5
DEGREES10 = 10
DEGREES15 = 15

POUNDS5 = 5
POUNDS10 = 10
NOWEIGHT = 0
STARTWEIGHT = 5
STARTPOSITION = 0.5

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

   protocolList = ['S', 'AB1', 'AB2', 'AB3', 'AB4', 'AB0']
   def __init__(self, _BFactor, protocol, pressure, minusDegrees, plusDegrees, cycles, ser, parent=None):
#     QThread.__init__(self, parent)
     super(Protocols, self).__init__()

     self.arduino = ser

     self.BFactor = _BFactor

     self.signals = WorkerSignals()

     self.isRunning = False

     self.degreeList = {0:5, 5:4, 10:3, 15:2, 20:1, 25:0, 30:0}

     self.I2Cstatus = 0

     self.protocol = protocol
     self.pressure = pressure
     self.minusDegrees = minusDegrees
     self.plusDegrees = plusDegrees
     self.cycles = cycles
     self.startPosition = 0

     print(self.protocol, self.protocolList)
     if(self.protocol not in self.protocolList):
        return

     self.isRunning = False
     self.exitFlag = threading.Event()


   @pyqtSlot()
   def run(self):
     print("Thread start")

     self.isRunning = True

     if(self.protocol[0] == 'S'):
       print('setup')
       self.setup()

     if(self.protocol[0:2] == 'AB'):
       self.ABProtocol(self.protocol, self.pressure, self.minusDegrees, self.plusDegrees, self.cycles)
     print('thread END')
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

   def status(self, positionA, positionB, steps, pressure):
#     print('>> A {} B {} C {} Pressure {}'.format(positionA, positionB, steps, pressure))
     self.startPosition = positionA
     self.pressure = pressure

   def ABProtocol(self, protocol, pressure, minusDegrees, plusDegrees, cycles):
     print('*** {} {}lbs minusDegrees {} plusDegrees {} cycles {}'.format(protocol, pressure, minusDegrees, plusDegrees, cycles))

     print('sendCalibration')
     self.arduino.send('L1')
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

     if(protocol == 'AB1'):
        self.protocol1(pressure, minusDegrees, plusDegrees, cycles)
     if(protocol == 'AB2'):
        self.protocol2(pressure, minusDegrees, plusDegrees, cycles)
     if(protocol == 'AB3'):
        self.protocol3(pressure, minusDegrees, plusDegrees, cycles)
     if(protocol == 'AB4'):
        self.protocol4(pressure, minusDegrees, plusDegrees, cycles)

   def killProtocol(self):
     self.isRunning = False

   def setup(self):
     inches = self.degreeList[DEGREES10] #set as initial angle
     position = int(inches * self.BFactor / 6.0)


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

   def setToDistance(self, degrees):
     inches = self.degreeList[degrees] #set as initial angle
     position = int(inches * self.BFactor / 6.0)
     print(' positioned to {} deg {} in. {} pos'.format(degrees, inches, position))

     command = 'A13{}'.format(inches)
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


   def status(self, positionA, positionB, steps, pressure):
#     print('>> A {} B {} C {} Pressure {}'.format(positionA, positionB, steps, pressure))
     self.startPosition = positionA
     self.pressure = pressure
     self.signals.APressure.emit('Pressure at {} lbs'.format(self.pressure))

   def resetA(self):
     self.signals.progress.emit('>>Degrees {}'.format(DEGREES15))
     if(self.setToDistance(DEGREES15) == False):
       self.signals.finished.emit(False)
       return False
     self.signals.progress.emit('Degrees {}'.format(DEGREES15))

     self.signals.progress.emit('>>Moved to start {}'.format(NOWEIGHT))
     if(self.setAToDistance(NOWEIGHT) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Moved to start {}'.format(NOWEIGHT))
     return True


   def protocol0(self, pressure):
     return

     inches = (self.startPosition  * 6.0)/ self.BFactor
     print('A Position {} Pressure {} lbs {:.2f} inches'.format(self.startPosition, self.pressure, inches))

     self.signals.progress.emit('A Positioned at {:.1f} in. for start.'.format(inches))
     self.signals.finished.emit(True)


   def protocol1(self, pressure, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES15))
     if(self.setToDistance(DEGREES15) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to {} Degrees'.format(DEGREES15))

     currentPressure = 3
     for cycle in range(1, cycles+1):

       currentPressure = POUNDS10
       currentDegrees = plusDegrees

       self.signals.progress.emit('>>Cycle {} {} Degrees'.format(cycle, plusDegrees))
       if(self.setToDistance(plusDegrees) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Cycle {} {} Degrees'.format(cycle, plusDegrees))

       self.signals.progress.emit('>>Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, POUNDS10))
       self.exitFlag.wait(timeout=5)

       currentPressure += 3
       for push in range(currentPressure, pressure+1, 3):
         self.signals.progress.emit('>>Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, push))
         if(self.setToPressure(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, push))
         self.exitFlag.wait(timeout=5)

       self.signals.progress.emit('>>Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))

       currentDegrees += 5
       for push in range(currentDegrees, minusDegrees+1, 5):
         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, push))
         if(self.setToDistance(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, push))
         self.exitFlag.wait(timeout=3)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')

   def protocol2(self, pressure, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES15))
     if(self.setToDistance(DEGREES15) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to {} Degrees'.format(DEGREES15))

     for cycle in range(1, cycles+1):
       currentDegrees = plusDegrees
       l = 1
       currentPressure = POUNDS10
       PMet = False
       DMet = False
       while True:

         self.signals.progress.emit('>>Cycle {} {} Degrees'.format(cycle, plusDegrees))
         if(self.setToDistance(plusDegrees) == False):
            self.signals.finished.emit(False)
            return
         self.signals.progress.emit('Cycle {} {} Degrees'.format(cycle, plusDegrees))
  
         self.signals.progress.emit('>>Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))
         if(self.setToPressure(POUNDS10) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))
         self.exitFlag.wait(timeout=5)
  
         if(currentPressure + 3 > pressure):
           PMet = True
         if(not PMet):
           currentPressure += 3
         if(PMet and DMet):
           break

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)
  
         currentPressure -= 1
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)
  
         if(currentPressure + 3 > pressure):
           PMet = True
         if(not PMet):
           currentPressure += 3
         if(PMet and DMet):
           break

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)
  
         currentPressure -= 1
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs'.format(cycle, currentPressure))

         if(currentDegrees + (5 * l) > minusDegrees):
           DMet = True
         if(not DMet):
           currentDegrees += (5 * l)
         if(PMet and DMet):
           break

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')



   def protocol3(self, pressure, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES15))
     if(self.setToDistance(DEGREES15) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to {} Degrees'.format(DEGREES15))

     for cycle in range(1, cycles+1):

       currentPressure = POUNDS10
       currentDegrees = plusDegrees

       self.signals.progress.emit('>>Cycle {} {} Degrees'.format(cycle, plusDegrees))
       if(self.setToDistance(plusDegrees) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Cycle {} {} Degrees'.format(cycle, plusDegrees))

       self.signals.progress.emit('>>Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS10) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure to {} lbs hold 5 secs'.format(cycle, POUNDS10))
       self.exitFlag.wait(timeout=5)

       print(currentPressure)
       currentPressure += 5
       print(currentPressure)

       for push in range(currentPressure, pressure+1, 5):
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, push))
         if(self.setToPressure(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, push))
         self.exitFlag.wait(timeout=5)

       self.signals.progress.emit('>>Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))
       if(self.setToPressure(POUNDS5) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))

       currentDegrees += 5
       for push in range(currentDegrees, minusDegrees+1, 5):
         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, push))
         if(self.setToDistance(push) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, push))
         self.exitFlag.wait(timeout=3)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


   def protocol4(self, pressure, minusDegrees, plusDegrees, cycles):

     self.signals.progress.emit('>>Set to start {} Degrees'.format(DEGREES15))
     if(self.setToDistance(DEGREES15) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Set to {} Degrees'.format(DEGREES15))

     for cycle in range(1, cycles+1):
       currentDegrees = plusDegrees
       l = 1
       currentPressure = POUNDS10
       PMet = False
       DMet = False
       while True:

         self.signals.progress.emit('>>Cycle {} {} Degrees'.format(cycle, plusDegrees))
         if(self.setToDistance(plusDegrees) == False):
            self.signals.finished.emit(False)
            return
         self.signals.progress.emit('Cycle {} {} Degrees'.format(cycle, plusDegrees))
  
         self.signals.progress.emit('>>Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))
         if(self.setToPressure(POUNDS10) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure to {} lbs'.format(cycle, POUNDS10))
         self.exitFlag.wait(timeout=5)
  
         if(currentPressure + 5 > pressure):
           PMet = True
         if(not PMet):
           currentPressure += 5
         if(PMet and DMet):
           break

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)
  
         currentPressure -= 1
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)
  
         if(currentPressure + 5 > pressure):
           PMet = True
         if(not PMet):
           currentPressure += 5
         if(PMet and DMet):
           break

         self.signals.progress.emit('>>Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs hold 5 secs'.format(cycle, currentPressure))
         self.exitFlag.wait(timeout=5)
  
         currentPressure -= 1
         self.signals.progress.emit('>>Cycle {} Pressure {} lbs'.format(cycle, currentPressure))
         if(self.setToPressure(currentPressure) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} Pressure {} lbs'.format(cycle, currentPressure))

         if(currentDegrees + (5 * l) > minusDegrees):
           DMet = True
         if(not DMet):
           currentDegrees += (5 * l)
         if(PMet and DMet):
           break

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         if(self.setToDistance(currentDegrees) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 3 secs'.format(cycle, currentDegrees))
         self.exitFlag.wait(timeout=3)

     if(self.resetA()):
       self.signals.finished.emit(True)
       self.signals.progress.emit('')


   def setI2CStatus(self, channel):
      self.I2Cstatus = 1
      print('self.I2Cstatus = 1')

