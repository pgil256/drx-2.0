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
    APressure = pyqtSignal(str)
    progress = pyqtSignal(str)

'''
Incremental Increase/decrease max at 5
Left 20     -20   0"
Left 15     -15   1/8"
Left 10     -10   1/4"
Left 5        -5     3/8"
CENTER      0     1/2"
Right 5     +5     5/8"
Right 10  +10   3/4"
Right 15  +15   7/8"
Right 20  +20    1"

 1 degree = .025 inch
'''
DEGREES10 = 4
DEGREES0 = 0

NOWEIGHT = 0
STARTWEIGHT = 5
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

#     self.setToPressure(self.pressure)

   def setToPressure(self, desiredPressure):

     while self.running:
       command = 'I{}'.format(12)
       self.arduino.send(command)                #transmit data serially 

       command = 'P{}'.format(desiredPressure)
       self.arduino.send(command)                #transmit data serially 
       print('cmd {}'.format(command.strip()))

       time.sleep(0.5)

     print('end')

 
class Protocols(QtCore.QRunnable):
   progress = pyqtSignal(str)
   completed = pyqtSignal()
   finished = pyqtSignal()

   protocol = ''
   pressure = 0
   cycles = 0

   protocolList = ['S', 'C1', 'C2', 'C3', 'C0']
   def __init__(self, _CFactor, protocol, leftDegrees, rightDegrees, cycles, ser, config, parent=None):
#     QThread.__init__(self, parent)
     super(Protocols, self).__init__()

     self.arduino = ser

     self.CFactor = _CFactor
     self.config = config

     self.signals = WorkerSignals()

     self.isRunning = False

     self.degreeList = {1:.025, 5:.625, 10:.75, 15:.875, 20:1, 0:.5, -5:.375, -10:.25, -15:.125, -20:0}

     self.I2Cstatus = 0

     self.protocol = protocol
     self.leftDegrees = leftDegrees
     self.rightDegrees = rightDegrees
     self.cycles = cycles

     self.startPosition = 0
     self.pressure = 0

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

     if(self.protocol[0] == 'C'):
       self.CProtocol(self.protocol, self.leftDegrees, self.rightDegrees, self.cycles)
     print('thread END')
#     self.completed.emit()
#     self.signals.finished.emit()  # Done

   def stop(self):
     print('stop')
     self.isRunning = False
     self.exitFlag.set()

     try:
       self.arduino.send('X')                #transmit data serially 
     except Exception as e:
       print(str(e))


   def CProtocol(self, protocol, leftDegrees, rightDegrees, cycles):
     print('*** {} degrees {}/{} cycles {}'.format(protocol, leftDegrees, rightDegrees, cycles))

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

     if(protocol == 'C1'):
        self.protocol1(-leftDegrees, cycles)
     if(protocol == 'C2'):
        self.protocol2(rightDegrees, cycles)
     if(protocol == 'C3'):
        self.protocol3(-leftDegrees, rightDegrees, cycles)
     if(protocol == 'C0'):
        self.protocol0(leftDegrees)

   def status(self, positionA, positionB, steps, pressure):
#     print('>> A {} B {} C {} Pressure {}'.format(positionA, positionB, steps, pressure))
#     self.startPosition = positionA
     self.pressure = pressure
     self.signals.APressure.emit('Pressure at {} lbs'.format(self.pressure))


   def killProtocol(self):
     self.isRunning = False

   def setup(self):
     inches = self.degreeList[10] #set as initial angle
     position = int(inches * self.CFactor)
     self.setToDistance(position)
     print(' positioned to {} in.'.format(inches))

   def I2CStatus(self):
     self.I2Cstatus = True

   def setToPosition(self, speed, position):
     pass

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
     print(degrees)

     position = self.config.CMarks['{:.1f}'.format(degrees)]
     print(' positioned to {} degrees pos {}'.format(degrees, position))
     command = 'K{}'.format(position)
     self.arduino.send(command)
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

   def resetA(self):
     self.signals.progress.emit('>>Move to start {} Degrees'.format(DEGREES0))
     if(self.setToDistance(DEGREES0) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Move to start {} Degrees'.format(DEGREES0))

     self.signals.progress.emit('>>Moved to start {}'.format(NOWEIGHT))
     if(self.setAToDistance(NOWEIGHT) == False):
        self.signals.finished.emit(False)
        return False
     self.signals.progress.emit('Moved to start {}'.format(NOWEIGHT))
     return True

   def protocol0(self, degrees):

     self.threadpool = QtCore.QThreadPool()
     print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
     self.pressureWorker = KeepPressure(self.ser, 3)
     self.threadpool.start(self.pressureWorker)

     if(self.setToDistance(degrees) == False):
        self.signals.finished.emit(False)
        return
     print(' positioned to {} in.'.format(inches))
     time.sleep(10)
     self.pressureWorker.stop()

     self.signals.finished.emit(True)


   def protocol1(self, degrees, cycles):

     self.signals.progress.emit('>>Pressure to {} lbs'.format(STARTWEIGHT))
     if(self.setToPressure(STARTWEIGHT) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure to {} lbs'.format(STARTWEIGHT))

     dir = 1
     if(degrees < 0):
       dir = -1
     for cycle in range(1, cycles+1):
       self.signals.progress.emit('>>Cycle {} at {} Degrees'.format(cycle, DEGREES0))
       if(self.setToDistance(DEGREES0) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Cycle {} at {} Degrees'.format(cycle, DEGREES0))

       push = 2.5
       while (push <= abs(degrees)):
#       self.setToPressure(5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         if(self.setToDistance(push * dir) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         self.exitFlag.wait(timeout=5)

         push = push + 2.5

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 10 secs'.format(cycle, degrees))
       if(self.setToDistance(degrees * dir) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 10 secs'.format(cycle, degrees))
       self.exitFlag.wait(timeout=10)

     if(self.resetA()):
       self.signals.finished.emit(True)



   def protocol2(self, degrees, cycles):

     self.signals.progress.emit('>>Pressure to {} lbs'.format(STARTWEIGHT))
     if(self.setToPressure(STARTWEIGHT) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure to {} lbs'.format(STARTWEIGHT))

     dir = 1
     if(degrees < 0):
       dir = -1
     for cycle in range(1, cycles+1):
       self.signals.progress.emit('>>Cycle {} at {} Degrees'.format(cycle, DEGREES0))
       if(self.setToDistance(DEGREES0) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Cycle {} at {} Degrees'.format(cycle, DEGREES0))

       push = 2.5
       while (push <= abs(degrees)):
#       self.setToPressure(5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         if(self.setToDistance(push * dir) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         self.exitFlag.wait(timeout=5)

         push = push + 2.5

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 10 secs'.format(cycle, degrees))
       if(self.setToDistance(degrees * dir) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 10 secs'.format(cycle, degrees))
       self.exitFlag.wait(timeout=10)

     if(self.resetA()):
       self.signals.finished.emit(True)


   def protocol3(self, leftDegrees, rightDegrees, cycles):

     self.signals.progress.emit('>>Pressure to {} lbs'.format(STARTWEIGHT))
     if(self.setToPressure(STARTWEIGHT) == False):
       self.signals.finished.emit(False)
       return
     self.signals.progress.emit('Pressure to {} lbs'.format(STARTWEIGHT))

     for cycle in range(1, cycles+1):
       self.signals.progress.emit('>>Cycle {} at {} Degrees'.format(cycle, DEGREES0))
       if(self.setToDistance(DEGREES0) == False):
          self.signals.finished.emit(False)
          return
       self.signals.progress.emit('Cycle {} at {} Degrees'.format(cycle, DEGREES0))

       dir = -1
       push = 2.5
       while (push <= abs(leftDegrees)):
#       self.setToPressure(5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         if(self.setToDistance(push * dir) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         self.exitFlag.wait(timeout=5)

         push = push + 2.5

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 10 secs'.format(cycle, leftDegrees * dir))
       if(self.setToDistance(leftDegrees * dir) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 10 secs'.format(cycle, leftDegrees * dir))
       self.exitFlag.wait(timeout=10)


       self.signals.progress.emit('>>Move to start {} Degrees'.format(DEGREES0))
       if(self.setToDistance(DEGREES0) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Move to start {} Degrees'.format(DEGREES0))

       dir = 1
       push = 2.5
       while (push <= abs(rightDegrees)):
#       self.setToPressure(5)

         self.signals.progress.emit('>>Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         if(self.setToDistance(push * dir) == False):
           self.signals.finished.emit(False)
           return
         self.signals.progress.emit('Cycle {} {} Degrees hold 5 secs'.format(cycle, push * dir))
         self.exitFlag.wait(timeout=5)

         push = push + 2.5

       self.signals.progress.emit('>>Cycle {} {} Degrees hold 10 secs'.format(cycle, rightDegrees * dir))
       if(self.setToDistance(rightDegrees * dir) == False):
         self.signals.finished.emit(False)
         return
       self.signals.progress.emit('Cycle {} {} Degrees hold 10 secs'.format(cycle, rightDegrees * dir))
       self.exitFlag.wait(timeout=10)

     if(self.resetA()):
       self.signals.finished.emit(True)


